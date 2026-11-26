// Tabla from recorded strokes, as an instrument of its own next to the main one.
//
//     sclang host/synth/tabla.scd
//
// Runs its own sound server (port 57142) and takes strokes by OSC on port 57143, like the
// mridangam patch (57140 / 57141) and apart from the piano patch that xentool plays:
//
//     /tabla/stroke  <bol> <loudness 0..1>      e.g.  /tabla/stroke Dhin 0.8
//     /tabla/gain    <0..2>
//     /tabla/ping                                answered with /tabla/pong <number of bols>
//
// Samples: Subodh Deolekar, "Tabla strokes dataset" (2020, Zenodo, DOI 10.5281/zenodo.4327350,
// CC BY 4.0), in the selection of the bolbox kit (eleven bols, ten takes each, trimmed, mono),
// with that kit's gain per bol. A stroke picks one of the ten takes at random.
//
// Bols: the kit's table says which samples sound for a bol (reference/music/tabla/kit/kit.scd,
// written by host/synth/tabla_kit.py from host/tutor/percussion.py). Recorded: Ge Ka Na Tin
// Tun Ta Ti Te Re Dha Dhun. THIS PROJECT'S CHOICE, not a statement of any source: a bol with
// no recording of its own that begins with "Dh" (Dhin, Dhi, Dhe) is the open left-drum stroke
// Ge and the right-drum stroke of the same name (Tin, Ti, Te) struck together; bols of a
// timbre class without any recording get a stand-in (Din and Di sound as Tin, Kra as Ka).
// Other spellings sound as the recorded bol of their timbre class (Kat, Ke = Ka; Ga = Ge;
// Ra = Ta), after the classes of the CompMusic Tabla Solo dataset.
//
// The tutor also sends usul strokes here as tabla bols (dum = Ge, tek = Na, ...): a stand-in
// for a frame drum, chosen in host/tutor/percussion.py.
//
// The kit is looked for in reference/music/tabla/kit next to the repository's host folder, or
// where the environment variable OPENXEN_TABLA_KIT points.

~patchDir = thisProcess.nowExecutingPath !? { |p| PathName(p).pathOnly } ?? { File.getcwd };
~kitDir = "OPENXEN_TABLA_KIT".getenv ?? { (~patchDir +/+ "../../reference/music/tabla/kit").standardizePath };
~tablaGain = 1.0;

~tabla = Server(\tabla, NetAddr("127.0.0.1", 57142));
~tabla.options.numBuffers = 1024;
~tabla.options.memSize = 65536;

~tabla.waitForBoot({
    var kit = thisProcess.interpreter.executeFile(~kitDir +/+ "kit.scd");
    if(kit.isNil) {
        "tabla: no kit at % (run host/synth/tabla_kit.py)".format(~kitDir).postln;
        kit = (samples: (), bols: ());
    };

    // sample -> [linear gain, array of Buffers]
    ~tablaSamples = ();
    kit[\samples].keysValuesDo { |name, pair|
        ~tablaSamples[name] = [pair[0].dbamp, pair[1].collect { |file| Buffer.read(~tabla, ~kitDir +/+ file) }];
    };
    ~tablaBols = kit[\bols];

    SynthDef(\tablaStroke, { |buf, amp = 0.5, out = 0|
        var sig = PlayBuf.ar(1, buf, BufRateScale.kr(buf), doneAction: 2);
        Out.ar(out, (sig * amp) ! 2);
    }).send(~tabla);
    ~tabla.sync;

    // a bol -> its samples, struck together; loudness 0..1
    ~tablaPlay = { |bol, loud = 0.7|
        var parts = ~tablaBols[bol.asString.toLower.asSymbol];
        if(parts.notNil and: { parts.size > 0 }) {
            var amp = loud.clip(0, 1).linexp(0, 1, 0.1, 0.6) * ~tablaGain;
            ~tabla.makeBundle(nil, {         // one bundle: the two drums of a composed bol start together
                parts.do { |name|
                    var sample = ~tablaSamples[name];
                    if(sample.notNil and: { sample[1].size > 0 }) {
                        Synth(\tablaStroke, [\buf, sample[1].choose, \amp, amp * sample[0]], ~tabla);
                    };
                };
            });
        } {
            "tabla: no bol %".format(bol).postln;
        };
    };

    thisProcess.openUDPPort(57143);
    OSCdef(\tablaStroke, { |msg| ~tablaPlay.value(msg[1], msg[2] ? 0.7) }, '/tabla/stroke', recvPort: 57143);
    OSCdef(\tablaGain, { |msg| ~tablaGain = (msg[1] ? 1).clip(0, 2) }, '/tabla/gain', recvPort: 57143);
    OSCdef(\tablaPing, { |msg, time, addr| addr.sendMsg('/tabla/pong', ~tablaBols.size) }, '/tabla/ping', recvPort: 57143);

    "tabla ready: % bols, % samples; OSC /tabla/stroke on port 57143".format(
        ~tablaBols.size, ~tablaSamples.values.collect({ |s| s[1].size }).sum).postln;
});
