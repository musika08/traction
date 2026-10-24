// G-Helper - https://github.com/seerge/g-helper - app/Ally/AllyControl.cs
// Copyright seerge and contributors, licensed GPL-3.0. Commit c09017453d9ed0c52261b67a48d02bd55232e6ac.
// Modified for Traction (ported to C# 5 / .NET Framework 4.8), 2026
//
// Ported subset (the controller section below): the controller mode report of ApplyMode ([0x5A,0xD1,0x01,0x01,mode],
// Gamepad 1, Mouse 3) and the grip vibration reports of SetDeadzones ([0x5A,0xD1,0x06,0x02,s,s], and
// [0x5A,0xD1,0x1C,0x02,s,s] on the Xbox Ally). The rest of this file (the command protocol and the other commands)
// is Traction's own.

using System;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using Ally.Shared;

namespace Traction.Helper
{
    // One JSON object per line.
    //   request {"id":n,"cmd":"name","args":{...}}
    //   reply   {"id":n,"ok":bool,"message":"","data":...}
    // Fixed command list; unknown commands, unknown args and wrongly typed args are refused before any hardware call.
    // The controller, touchscreen and foreground commands answer exactly as Overdrive 0.1.0's helper did.
    public class TractionCore
    {
        public const string Version = "0.1.0";

        private static readonly string[] None = new string[0];

        // cmd -> allowed arg names
        private static readonly Dictionary<string, string[]> Commands = new Dictionary<string, string[]>
        {
            { "hello", None },
            { "frame_sample", None },
            { "foreground", None },
            { "armoury_state", None },
            { "armoury_stop", None },
            { "armoury_restore", new[] { "recorded", "running" } },
            { "controller_info", None },
            { "set_controller_mode", new[] { "mode" } },
            { "set_vibration", new[] { "strength" } },
            { "get_touchscreen", None },
            { "set_touchscreen", new[] { "enabled" } },
            { "set_bindings", new[] { "zone", "slots", "watch" } },
        };

        private static readonly string[] TopLevel = { "id", "cmd", "args" };

        // The only commands allowed on a device that is not an Ally (an allow-list of reads, so a command added later
        // is refused there unless it is listed here on purpose).
        public static readonly string[] ReadCommands =
        {
            "hello", "frame_sample", "foreground", "armoury_state", "controller_info", "get_touchscreen"
        };

        // The ASUS controller (mode, grip vibration). Set after construction; null means not available.
        public IAsusHid Hid { get; set; }

        // BIOS SystemProductName; the Xbox Ally family ("ROG Xbox Ally X RC73XA_RC73XA") gets a second vibration report.
        public string ProductName { get; set; }

        public const string ControllerUnavailable = "Controller control is not available.";

        // Touchscreen and the foreground app. Set after construction; null means not available. Named SystemControls
        // rather than System, which would hide the System namespace inside this class.
        public ISystemControls SystemControls { get; set; }

        // Whether Windows still sees the gamepad (set_bindings' safety net). Set after construction; null means
        // set_bindings is not available.
        public IPadCheck PadCheck { get; set; }

        public const string PadNotSeenMessage = "Windows does not see the gamepad, so the buttons were not changed.";

        public const string SystemUnavailable = "Touchscreen and graphics control is not available.";

        public static IEnumerable<string> CommandNames { get { return Commands.Keys; } }

        public const string NotAllyMessage = "Traction supports the ROG Ally family only";

        private readonly IAdl adl;
        private readonly bool ally;
        private readonly JavaScriptSerializer json = new JavaScriptSerializer();
        private readonly ArmouryCommands armoury;
        private readonly Action<int> sleep;

        public TractionCore(IAdl adl, IServices services, bool ally)
            : this(adl, services, ally, System.Threading.Thread.Sleep)
        {
        }

        // sleep is injectable so tests record the delays instead of waiting.
        public TractionCore(IAdl adl, IServices services, bool ally, Action<int> sleep)
        {
            this.adl = adl;
            this.ally = ally;
            this.sleep = sleep ?? System.Threading.Thread.Sleep;
            this.armoury = new ArmouryCommands(services, this.sleep);
        }

        // Never throws: every line gets exactly one single-line reply.
        public string HandleLine(string line)
        {
            object id = null;
            try
            {
                object parsed;
                try { parsed = json.DeserializeObject(line); }
                catch (Exception ex) { return ProtocolKit.Reply(null, false, "Malformed request: " + ex.Message, null); }

                var req = parsed as Dictionary<string, object>;
                if (req == null) return ProtocolKit.Reply(null, false, "Malformed request: expected a JSON object.", null);

                object rawId;
                if (req.TryGetValue("id", out rawId))
                {
                    int n;
                    if (!ProtocolKit.TryInt(rawId, out n)) return ProtocolKit.Reply(null, false, "Malformed request: id must be an integer.", null);
                    id = n;
                }
                else return ProtocolKit.Reply(null, false, "Malformed request: id is missing.", null);

                foreach (string key in req.Keys)
                    if (Array.IndexOf(TopLevel, key) < 0) return ProtocolKit.Reply(id, false, "Unknown field '" + key + "'.", null);

                object rawCmd;
                req.TryGetValue("cmd", out rawCmd);
                string cmd = rawCmd as string;
                if (cmd == null || !Commands.ContainsKey(cmd))
                    return ProtocolKit.Reply(id, false, "Refused: unknown command '" + (cmd ?? "") + "'.", null);

                object rawArgs;
                Dictionary<string, object> args;
                if (!req.TryGetValue("args", out rawArgs) || rawArgs == null) args = new Dictionary<string, object>();
                else
                {
                    args = rawArgs as Dictionary<string, object>;
                    if (args == null) return ProtocolKit.Reply(id, false, "Malformed request: args must be an object.", null);
                }
                string argError = ProtocolKit.CheckArgs(Commands, cmd, args);
                if (argError != null) return ProtocolKit.Reply(id, false, argError, null);

                return Dispatch(id, cmd, args);
            }
            catch (Exception ex)
            {
                return ProtocolKit.Reply(id, false, ex.Message, null);
            }
        }

        private string Dispatch(object id, string cmd, Dictionary<string, object> args)
        {
            if (!ally && Array.IndexOf(ReadCommands, cmd) < 0) return ProtocolKit.Reply(id, false, NotAllyMessage, null);
            switch (cmd)
            {
                case "hello": return Hello(id);
                case "frame_sample": return FrameSample(id);
                case "foreground": return Foreground(id);
                case "armoury_state": return armoury.State(id);
                case "armoury_stop": return armoury.Stop(id);
                case "armoury_restore": return armoury.Restore(id, args);
                case "controller_info": return ControllerInfo(id);
                case "set_controller_mode": return SetControllerMode(id, args);
                case "set_vibration": return SetVibration(id, args);
                case "get_touchscreen": return GetTouchscreen(id);
                case "set_touchscreen": return SetTouchscreen(id, args);
                case "set_bindings": return SetBindings(id, args);
            }
            return ProtocolKit.Reply(id, false, "Refused: unknown command '" + cmd + "'.", null);
        }

        // ---------- commands ----------

        private string Hello(object id)
        {
            var d = new Dictionary<string, object>();
            d["version"] = Version;
            d["ally"] = ally;
            return ProtocolKit.Reply(id, true, "", d);
        }

        // One sample for Auto TDP, read only: the game's frame rate (AMD frame metrics; 0 = no game in front, null =
        // unavailable, with an error) and the graphics power (null unless 1..1000 W).
        private string FrameSample(object id)
        {
            var d = new Dictionary<string, object>();
            var errors = new List<string>();
            float? fps = null;
            try
            {
                fps = adl.GetFrameRate();
                if (!fps.HasValue) errors.Add("frame rate: " + (adl.Unavailable ?? "not available"));
            }
            catch (Exception ex) { errors.Add("frame rate: " + ex.Message); }
            bool supported = true;
            try { supported = adl.FrameRateSupported; } catch (Exception) { }
            int? power = null;
            try
            {
                GpuSensors g = adl.GetGpuSensors();
                if (g != null) power = InRange(g.GfxPowerW, 1, 1000);
            }
            catch (Exception ex) { errors.Add("gpu power: " + ex.Message); }
            d["supported"] = supported;
            d["fps"] = fps.HasValue ? (object)fps.Value : null;
            d["gpuPowerW"] = power;
            d["errors"] = errors;
            return ProtocolKit.Reply(id, true, "", d);
        }

        private static int? InRange(int? v, int lo, int hi)
        {
            return v.HasValue && v.Value >= lo && v.Value <= hi ? v : null;
        }

        // ---------- ASUS controller (G-Helper app/Ally/AllyControl.cs ApplyMode and SetDeadzones) ----------

        private bool IsXbox()
        {
            return ProductName != null && ProductName.IndexOf("Xbox", StringComparison.Ordinal) >= 0;
        }

        private string ControllerInfo(object id)
        {
            if (Hid == null) return ProtocolKit.Reply(id, false, ControllerUnavailable, null);
            HidInfo info = Hid.Find();
            bool found = info != null && info.Found;
            var d = new Dictionary<string, object>();
            d["found"] = found;
            d["pid"] = found ? "0x" + info.Pid.ToString("X4") : null;
            d["xbox"] = IsXbox();
            return ProtocolKit.Reply(id, true, "", d);
        }

        private string SetControllerMode(object id, Dictionary<string, object> args)
        {
            object raw;
            if (!args.TryGetValue("mode", out raw)) return ProtocolKit.Reply(id, false, "Refused: 'mode' is required.", null);
            string mode = raw as string;
            // G-Helper ControllerMode: Gamepad = 1, Mouse = 3 ("desktop").
            byte m = mode == "gamepad" ? (byte)1 : mode == "desktop" ? (byte)3 : (byte)0;
            if (m == 0) return ProtocolKit.Reply(id, false, "Refused: controller mode must be gamepad or desktop.", null);
            var d = new Dictionary<string, object>();
            d["mode"] = mode;
            return WriteController(id, d, new byte[] { AsusHid.INPUT_ID, 0xD1, 0x01, 0x01, m });
        }

        private string SetVibration(object id, Dictionary<string, object> args)
        {
            int strength;
            string err;
            if (!ProtocolKit.GetInt(args, "strength", out strength, out err)) return ProtocolKit.Reply(id, false, err, null);
            if (strength < 0 || strength > 100) return ProtocolKit.Reply(id, false, "Refused: vibration strength must be a whole number from 0 to 100.", null);
            byte s = (byte)strength;
            var reports = new List<byte[]> { new byte[] { AsusHid.INPUT_ID, 0xD1, 0x06, 0x02, s, s } };
            if (IsXbox()) reports.Add(new byte[] { AsusHid.INPUT_ID, 0xD1, 0x1C, 0x02, s, s });
            var d = new Dictionary<string, object>();
            d["strength"] = strength;
            return WriteController(id, d, reports.ToArray());
        }

        // Pads each report to the controller collection's feature report length and sends them in order; the first
        // failure stops and is reported.
        private string WriteController(object id, Dictionary<string, object> data, params byte[][] reports)
        {
            string err = SendReports(true, reports);
            return err != null ? ProtocolKit.Reply(id, false, err, null) : ProtocolKit.Reply(id, true, "", data);
        }

        // Null when every report was sent, otherwise the first error. Nothing is sent unless every report fits the
        // feature report. stopOnError false still tries the remaining reports after a failure (the factory reset).
        private string SendReports(bool stopOnError, params byte[][] reports)
        {
            return SendReports(stopOnError, 1, reports);
        }

        // findAttempts > 1 looks for the controller that many times, FindRetryMs apart, before giving up (the factory
        // reset: a controller that just dropped off may take a moment to come back).
        private string SendReports(bool stopOnError, int findAttempts, params byte[][] reports)
        {
            if (Hid == null) return ControllerUnavailable;
            HidInfo info = null;
            for (int a = 1; a <= findAttempts; a++)
            {
                info = Hid.Find();
                if (info != null && info.Found) break;
                if (a < findAttempts) sleep(FindRetryMs);
            }
            if (info == null || !info.Found) return AsusHid.NotFound;
            foreach (byte[] r in reports)
                if (info.FeatureLength < r.Length)
                    return "Refused: the controller's feature report is only " + info.FeatureLength + " bytes.";
            string first = null;
            foreach (byte[] r in reports)
            {
                var padded = new byte[info.FeatureLength];
                Array.Copy(r, padded, r.Length);
                string err;
                if (Hid.SetFeature(padded, out err)) continue;
                if (first == null) first = err ?? "The controller refused the report.";
                if (stopOnError) break;
            }
            return first;
        }

        // ---------- button bindings (G-Helper app/Ally/AllyControl.cs BindZone; see Bindings.cs) ----------

        public const int PadPolls = 10;          // 10 x 500 ms = 5 s, as the probe waited
        public const int PadPollMs = 500;
        public const int ConfirmPolls = 4;       // seen at 4 polls in a row (1.5 s steady, 2 s after the write at least)
        public const int ResetFindAttempts = 3;  // the factory reset looks for the controller up to 3 times
        public const int FindRetryMs = 1000;

        // Writes one zone, then watches the gamepads: every XInput pad (0-3) seen before the write must be seen again
        // at ConfirmPolls polls in a row; when they are not back by the 10th poll (5 s), or go again after it, the full
        // factory set is written at once. Refused without a write when no gamepad is seen beforehand (no safety net).
        // watch false (Desktop mode, where Windows sees no gamepad): no check, no polling, no factory reset; the zone
        // is written and the reply says whether that worked.
        private string SetBindings(object id, Dictionary<string, object> args)
        {
            int zone;
            string err;
            if (!ProtocolKit.GetInt(args, "zone", out zone, out err)) return ProtocolKit.Reply(id, false, err, null);
            if (zone < 1 || zone > 9) return ProtocolKit.Reply(id, false, "Refused: zone must be a whole number from 1 to 9.", null);
            object raw;
            if (!args.TryGetValue("slots", out raw)) return ProtocolKit.Reply(id, false, "Refused: 'slots' is required.", null);
            var list = raw as object[];
            if (list == null || list.Length != 4) return ProtocolKit.Reply(id, false, "Refused: 'slots' must be a list of 4 binding codes.", null);
            var slots = new string[4];
            for (int i = 0; i < 4; i++)
            {
                slots[i] = list[i] as string;
                if (slots[i] == null) return ProtocolKit.Reply(id, false, "Refused: 'slots' must be a list of 4 binding codes.", null);
                if (!Bindings.IsAllowed(slots[i])) return ProtocolKit.Reply(id, false, "Refused: unknown binding code '" + slots[i] + "'.", null);
            }
            bool watch = true;
            if (args.ContainsKey("watch") && !ProtocolKit.GetBool(args, "watch", out watch, out err))
                return ProtocolKit.Reply(id, false, err, null);
            var written = new Dictionary<string, object>();
            written["zone"] = zone;

            if (!watch)
            {
                if (Hid == null) return ProtocolKit.Reply(id, false, ControllerUnavailable, null);
                err = SendReports(true, Bindings.ZoneReport(zone, slots));
                return err != null ? ProtocolKit.Reply(id, false, err, null) : ProtocolKit.Reply(id, true, "", written);
            }

            if (Hid == null || PadCheck == null) return ProtocolKit.Reply(id, false, ControllerUnavailable, null);
            int before = PadCheck.Pads() & 0x0F;
            if (before == 0) return ProtocolKit.Reply(id, false, PadNotSeenMessage, null);

            err = SendReports(true, Bindings.ZoneReport(zone, slots));
            if (err != null) return ProtocolKit.Reply(id, false, err, null);

            int steady = 0;
            for (int i = 1; i <= PadPolls + ConfirmPolls - 1; i++)
            {
                sleep(PadPollMs);
                if ((PadCheck.Pads() & before) == before)
                {
                    if (++steady >= ConfirmPolls) return ProtocolKit.Reply(id, true, "", written);
                }
                else
                {
                    steady = 0;
                    if (i >= PadPolls) break;   // not back within 5 s, or gone again after that
                }
            }

            err = SendReports(false, ResetFindAttempts, Bindings.FactoryReset(IsXbox()));
            var reset = new Dictionary<string, object>();
            reset["reset"] = err == null;
            if (err != null)
                return ProtocolKit.Reply(id, false, "The controller stopped responding and the factory reset failed: " + err, reset);
            return ProtocolKit.Reply(id, false, Bindings.ResetMessage, reset);
        }

        // ---------- touchscreen and foreground app ----------

        private string GetTouchscreen(object id)
        {
            if (SystemControls == null) return ProtocolKit.Reply(id, false, SystemUnavailable, null);
            TouchInfo t = SystemControls.GetTouchscreen();
            if (t == null) return ProtocolKit.Reply(id, false, "The touchscreen state could not be read.", null);
            if (t.Error != null) return ProtocolKit.Reply(id, false, t.Error, null);
            var d = new Dictionary<string, object>();
            d["found"] = t.Found;
            d["enabled"] = t.Found && t.Enabled;
            d["instanceId"] = t.Found ? t.InstanceId : null;
            return ProtocolKit.Reply(id, true, "", d);
        }

        // Starts the change and replies at once; the panel reads the state back on its next polls.
        private string SetTouchscreen(object id, Dictionary<string, object> args)
        {
            bool enabled;
            string err;
            if (!ProtocolKit.GetBool(args, "enabled", out enabled, out err)) return ProtocolKit.Reply(id, false, err, null);
            if (SystemControls == null) return ProtocolKit.Reply(id, false, SystemUnavailable, null);
            if (!SystemControls.StartSetTouchscreen(enabled, out err))
                return ProtocolKit.Reply(id, false, err ?? "The touchscreen change could not be started.", null);
            var d = new Dictionary<string, object>();
            d["enabled"] = enabled;
            return ProtocolKit.Reply(id, true, "", d);
        }

        private string Foreground(object id)
        {
            if (SystemControls == null) return ProtocolKit.Reply(id, false, SystemUnavailable, null);
            string exe = SystemControls.ForegroundExe();
            var d = new Dictionary<string, object>();
            d["exe"] = exe == null ? "" : exe.ToLowerInvariant();
            return ProtocolKit.Reply(id, true, "", d);
        }
    }
}
