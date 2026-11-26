// Tanpura drone, as an accompaniment of its own next to the main instrument.
//
//     sclang host/synth/tanpura.scd
//
// Runs its own sound server (port 57144) and takes commands by OSC on port 57145, like the
// mridangam (57140 / 57141) and tabla (57142 / 57143) patches and apart from the piano patch
// that xentool plays. The keyboard's own notes are not involved: whatever the player presses,
// a string of the drone is never cut.
//
//     /tanpura/start <seconds per string> <loudness 0..1> <Hz> <Hz> ...
//                        the strings in the order they are struck, round and round until
//                        stopped; a new start replaces the sounding drone
//     /tanpura/stop      the strings ring out
//     /tanpura/gain  <0..2>
//     /tanpura/ping      answered with /tanpura/pong <1 if sounding, else 0>
//
// The sound is a model, not a recording: a plucked string (Karplus-Strong) whose buzzing
// bridge (jawari) is imitated by a distortion that follows the string's own loudness, the
// same idea as xentool's supercollider/mpe_tanpura_xentool.scd. Which notes the strings get
// is decided by the tutor (host/tutor/library.py, drone_tuning), not here.

~tanpuraGain = 1.0;
~tanpura = Server(\tanpura, NetAddr("127.0.0.1", 57144));
~tanpura.options.memSize = 65536;

~tanpura.waitForBoot({
    SynthDef(\tanpuraString, { |freq = 130, amp = 0.3, decay = 9, pan = 0, out = 0|
        var burst = PinkNoise.ar * EnvGen.ar(Env.perc(0.003, 0.05));
        var string = Pluck.ar(burst, Impulse.kr(0), 0.1, freq.reciprocal, decay, 0.22);
        var follow = Amplitude.kr(string, 0.01, 0.4);
        var buzz = (string * (1 + (follow * 6))).tanh + (string.cubed * follow * 1.4);
        var sig = LeakDC.ar(string + (0.7 * (buzz - string)));
        sig = sig * EnvGen.kr(Env.linen(0.01, decay, 2.5, 1, \sine), doneAction: 2);
        Out.ar(out, Pan2.ar(sig * amp, pan));
    }).send(~tanpura);
    SynthDef(\tanpuraRoom, { |bus = 0|
        var sig = In.ar(bus, 2);
        ReplaceOut.ar(bus, Limiter.ar(FreeVerb2.ar(sig[0], sig[1], 0.3, 0.8, 0.5), 0.8));
    }).send(~tanpura);
    ~tanpura.sync;
    ~tanpuraStrings = Group.head(~tanpura);
    Synth.after(~tanpuraStrings, \tanpuraRoom);

    ~tanpuraStop = {
        ~tanpuraLoop !? { |loop| loop.stop };
        ~tanpuraLoop = nil;
    };
    ~tanpuraStart = { |pace, loud, freqs|
        ~tanpuraStop.value;
        freqs = freqs.select { |f| f.isNumber and: { f > 10 } and: { f < 4000 } };
        if(freqs.size > 0) {
            pace = pace.clip(0.2, 10);
            ~tanpuraLoop = Routine({
                loop {
                    freqs.do { |freq, i|
                        Synth(\tanpuraString, [
                            \freq, freq, \amp, loud.clip(0, 1).linexp(0, 1, 0.03, 0.5) * ~tanpuraGain,
                            \decay, (pace * freqs.size * 1.6).max(4), \pan, i.linlin(0, (freqs.size - 1).max(1), -0.4, 0.4)
                        ], ~tanpuraStrings);
                        pace.wait;
                    };
                };
            }).play(SystemClock);
        };
    };

    thisProcess.openUDPPort(57145);
    OSCdef(\tanpuraStart, { |msg| ~tanpuraStart.value(msg[1] ? 1, msg[2] ? 0.5, msg[3..]) }, '/tanpura/start', recvPort: 57145);
    OSCdef(\tanpuraStop, { ~tanpuraStop.value }, '/tanpura/stop', recvPort: 57145);
    OSCdef(\tanpuraGain, { |msg| ~tanpuraGain = (msg[1] ? 1).clip(0, 2) }, '/tanpura/gain', recvPort: 57145);
    OSCdef(\tanpuraPing, { |msg, time, addr| addr.sendMsg('/tanpura/pong', if(~tanpuraLoop.notNil, 1, 0)) }, '/tanpura/ping', recvPort: 57145);

    "tanpura ready: OSC /tanpura/start on port 57145".postln;
});
