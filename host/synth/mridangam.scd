// Mridangam from recorded strokes, as an instrument of its own next to the main one.
//
//     sclang host/synth/mridangam.scd
//
// Runs its own sound server (port 57140) and takes strokes by OSC on port 57141, so it
// neither shares a MIDI channel nor a synth with the piano patch that xentool plays:
//
//     /mridangam/stroke  <name> <loudness 0..1>      e.g.  /mridangam/stroke Thom 0.8
//     /mridangam/gain    <0..2>
//
// Strokes: Thom Num Tha Thi Dhin Dheem Cha Bheem Ta Tham. Each has several recorded
// loudness layers and several takes per layer; a stroke picks the layer for its loudness
// and one of its takes at random, so repetitions do not sound machine-made.
//
// It also answers MIDI notes with the kit's own numbers (36 Thom, 38 Num, 40 Tha, 41 Thi,
// 43 Dhin, 45 Dheem, 47 Cha, 48 Bheem, 50 Ta, 52 Tham) on ~midiChannel if that is set
// (zero-based; nil = MIDI off, the default, because the piano patch would play them too).
//
// Samples: reference/music/mridangam/kit, prepared by host/synth/mridangam_kit.py.

~patchDir = thisProcess.nowExecutingPath !? { |p| PathName(p).pathOnly } ?? { File.getcwd };
~kitDir = (~patchDir +/+ "../../reference/music/mridangam/kit").standardizePath;
~midiChannel = nil;
~gain = 1.0;
~noteMap = (36: \Thom, 38: \Num, 40: \Tha, 41: \Thi, 43: \Dhin, 45: \Dheem, 47: \Cha, 48: \Bheem, 50: \Ta, 52: \Tham);

~mridangam = Server(\mridangam, NetAddr("127.0.0.1", 57140));
~mridangam.options.numBuffers = 1024;
~mridangam.options.memSize = 65536;

~mridangam.waitForBoot({
    var kit = thisProcess.interpreter.executeFile(~kitDir +/+ "kit.scd");
    if(kit.isNil) { "mridangam: no kit at % (run host/synth/mridangam_kit.py)".format(~kitDir).postln };

    // stroke -> array of [power, Buffer], softest first
    ~strokes = ();
    kit.keysValuesDo { |name, list|
        ~strokes[name] = list.collect { |pair| [pair[0], Buffer.read(~mridangam, ~kitDir +/+ pair[1])] };
    };

    SynthDef(\mridangamStroke, { |buf, amp = 0.5, out = 0|
        var sig = PlayBuf.ar(1, buf, BufRateScale.kr(buf), doneAction: 2);
        Out.ar(out, (sig * amp) ! 2);
    }).send(~mridangam);
    ~mridangam.sync;

    // loudness 0..1 -> the takes whose power is nearest, one of them at random
    ~play = { |name, loud = 0.7|
        var list = ~strokes[name.asSymbol];
        if(list.notNil and: { list.size > 0 }) {
            var powers = list.collect(_[0]);
            var target = loud.clip(0, 1).linlin(0, 1, powers.minItem, powers.maxItem);
            var order = (0 .. list.size - 1).sort { |a, b| (powers[a] - target).abs < (powers[b] - target).abs };
            var pick = list[order.keep(3).choose];
            Synth(\mridangamStroke, [\buf, pick[1], \amp, loud.clip(0, 1).linexp(0, 1, 0.12, 1.0) * ~gain], ~mridangam);
        } {
            "mridangam: no stroke %".format(name).postln;
        };
    };

    thisProcess.openUDPPort(57141);
    OSCdef(\mridangamStroke, { |msg| ~play.value(msg[1], msg[2] ? 0.7) }, '/mridangam/stroke', recvPort: 57141);
    OSCdef(\mridangamGain, { |msg| ~gain = (msg[1] ? 1).clip(0, 2) }, '/mridangam/gain', recvPort: 57141);

    MIDIClient.init;
    MIDIIn.connectAll;
    MIDIdef.noteOn(\mridangamMidi, { |vel, num, chan|
        if(~midiChannel.notNil and: { chan == ~midiChannel } and: { vel > 0 }) {
            ~noteMap[num] !? { |name| ~play.value(name, vel / 127) };
        };
    });

    "mridangam ready: % strokes, % samples; OSC /mridangam/stroke on port 57141".format(
        ~strokes.size, ~strokes.values.collect(_.size).sum).postln;
});
