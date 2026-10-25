using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Web.Script.Serialization;
using Ally.Shared;

namespace Traction.Helper.Tests
{
    // Tiny runner in the house style: every public static parameterless method of HelperTests is a test.
    // Prints PASS/FAIL per test; the exit code is the number of failures.
    public static class TestRunner
    {
        public static int Main(string[] args)
        {
            int passed = 0, failed = 0;
            var tests = new List<MethodInfo>(typeof(HelperTests).GetMethods(BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly));
            tests.Sort((a, b) => string.CompareOrdinal(a.Name, b.Name));
            foreach (MethodInfo m in tests)
            {
                if (m.GetParameters().Length != 0) continue;
                try
                {
                    m.Invoke(null, null);
                    passed++;
                    Console.WriteLine("PASS " + m.Name);
                }
                catch (Exception ex)
                {
                    failed++;
                    Exception inner = (ex is TargetInvocationException && ex.InnerException != null) ? ex.InnerException : ex;
                    Console.WriteLine("FAIL " + m.Name + " : " + inner.Message);
                }
            }
            Console.WriteLine();
            Console.WriteLine("Helper tests: " + passed + " passed, " + failed + " failed, " + (passed + failed) + " total");
            return failed;
        }
    }

    public class TestFailure : Exception
    {
        public TestFailure(string message) : base(message) { }
    }

    public static class HelperTests
    {
        // ---------- helpers ----------

        private static readonly JavaScriptSerializer Json = new JavaScriptSerializer();

        private static void True(bool cond, string what) { if (!cond) throw new TestFailure(what); }

        private static void Equal(object expected, object actual, string what)
        {
            if (!object.Equals(expected, actual))
                throw new TestFailure(what + ": expected <" + expected + "> got <" + actual + ">");
        }

        private static void SeqEqual(IList<string> expected, IList<string> actual, string what)
        {
            string e = string.Join(" | ", expected), a = string.Join(" | ", actual);
            if (e != a) throw new TestFailure(what + ":\n  expected " + e + "\n  got      " + a);
        }

        private class Rig
        {
            public FakeAdl Adl = new FakeAdl();
            public FakeServices Services = new FakeServices();
            public FakeHidBus Bus = new FakeHidBus();
            public FakeSystemControls Sys = new FakeSystemControls();
            public FakePadCheck Pad = new FakePadCheck();
            public readonly List<int> Sleeps = new List<int>();
            public TractionCore Core;
            public Rig() : this(true) { }
            public Rig(bool ally)
            {
                Core = new TractionCore(Adl, Services, ally, ms => Sleeps.Add(ms));
                Core.Hid = new AsusHid(Bus);
                Core.PadCheck = Pad;
                Core.SystemControls = Sys;
                Core.ProductName = "ROG Ally X RC72LA_RC72LA";
            }

            public Dictionary<string, object> Send(string line)
            {
                string reply = Core.HandleLine(line);
                True(reply != null && reply.IndexOf('\n') < 0, "reply must be one line");
                return (Dictionary<string, object>)Json.DeserializeObject(reply);
            }
        }

        private static bool Ok(Dictionary<string, object> r) { return (bool)r["ok"]; }
        private static string Msg(Dictionary<string, object> r) { return (string)r["message"]; }

        // ---------- protocol ----------

        public static void Hello_ReportsVersionAndAlly()
        {
            var rig = new Rig();
            var r = rig.Send("{\"id\":1,\"cmd\":\"hello\"}");
            True(Ok(r), "hello ok");
            Equal(1, r["id"], "id echoed");
            var data = (Dictionary<string, object>)r["data"];
            Equal("0.1.0", data["version"], "version");
            Equal(true, data["ally"], "ally");
        }

        public static void UnknownCommand_Refused()
        {
            var rig = new Rig();
            var r = rig.Send("{\"id\":7,\"cmd\":\"set_charge_limit\",\"args\":{\"limit\":80}}");
            True(!Ok(r), "unknown command must be refused");
            Equal(7, r["id"], "id echoed");
            True(Msg(r).Contains("unknown command"), "message names the problem: " + Msg(r));
            Equal(0, rig.Bus.Writes.Count, "no hardware call");
        }

        // The commands that stayed in Overdrive are unknown here.
        public static void OverdriveCommands_Refused()
        {
            var rig = new Rig();
            int n = 0;
            foreach (string cmd in new[] { "status", "sensors", "set_mode", "set_power", "get_fans", "set_fans", "reset_fans",
                "get_fps_limit", "set_fps_limit", "get_cpu_boost", "set_cpu_boost", "get_power_mode", "set_power_mode",
                "get_auto_sr", "set_auto_sr" })
            {
                var r = rig.Send("{\"id\":" + (++n) + ",\"cmd\":\"" + cmd + "\"}");
                True(!Ok(r) && Msg(r).Contains("unknown command"), cmd + ": " + Msg(r));
            }
            Equal(0, rig.Bus.Writes.Count, "no hardware call");
        }

        public static void UnknownArg_Refused()
        {
            var rig = new Rig();
            var r = rig.Send("{\"id\":2,\"cmd\":\"set_vibration\",\"args\":{\"strength\":20,\"tdp\":40}}");
            True(!Ok(r), "unknown arg must be refused");
            True(Msg(r).Contains("tdp"), "message names the arg: " + Msg(r));
            Equal(0, rig.Bus.Writes.Count, "no hardware call");

            r = rig.Send("{\"id\":3,\"cmd\":\"hello\",\"args\":{\"x\":1}}");
            True(!Ok(r), "hello takes no args");

            r = rig.Send("{\"id\":4,\"cmd\":\"hello\",\"extra\":1}");
            True(!Ok(r), "unknown top-level field refused");
        }

        public static void Malformed_Json_ReturnsError_NotCrash()
        {
            var rig = new Rig();
            var r = rig.Send("{\"id\":1,\"cmd\":");
            True(!Ok(r), "malformed json refused");
            True(r.ContainsKey("id") && r["id"] == null, "id is null when it cannot be read");

            r = rig.Send("[1,2,3]");
            True(!Ok(r), "non-object refused");
            r = rig.Send("{\"id\":\"x\",\"cmd\":\"hello\"}");
            True(!Ok(r), "non-integer id refused");
            r = rig.Send("{\"id\":5,\"cmd\":\"set_vibration\",\"args\":{\"strength\":\"20\"}}");
            True(!Ok(r), "string where int expected refused");
            Equal(5, r["id"], "id echoed on bad arg type");
            r = rig.Send("{\"id\":6,\"cmd\":\"set_vibration\",\"args\":{\"strength\":20.5}}");
            True(!Ok(r), "fraction where int expected refused");
            Equal(0, rig.Bus.Writes.Count, "no hardware call");
        }

        public static void MainLoop_OneReplyPerLine_UntilEof()
        {
            var rig = new Rig();
            var input = new StringReader("not json at all\n\n{\"id\":9,\"cmd\":\"hello\"}\n{\"id\":10,\"cmd\":\"nope\"}\n");
            var output = new StringWriter();
            HelperMain.Run(input, output, rig.Core);
            string[] lines = output.ToString().Split(new[] { "\n" }, StringSplitOptions.RemoveEmptyEntries);
            Equal(3, lines.Length, "one reply per non-empty line");
            True(lines[1].Contains("\"id\":9") && lines[1].Contains("\"ok\":true"), "hello answered after a bad line: " + lines[1]);
        }

        public static void MainLoop_HardwareException_BecomesErrorReply()
        {
            var rig = new Rig();
            rig.Core.SystemControls = new ThrowingSystemControls();
            var r = rig.Send("{\"id\":11,\"cmd\":\"get_touchscreen\"}");
            True(!Ok(r), "exception reported as failure");
            True(Msg(r).Contains("read attempted"), "exception message passed on: " + Msg(r));
        }

        private class ThrowingSystemControls : ISystemControls
        {
            public TouchInfo GetTouchscreen() { throw new InvalidOperationException("read attempted"); }
            public bool StartSetTouchscreen(bool enabled, out string err) { throw new InvalidOperationException("write attempted"); }
            public string ReadGpuSettings(out string err) { throw new InvalidOperationException("read attempted"); }
            public bool WriteGpuSettings(string value, out string err) { throw new InvalidOperationException("write attempted"); }
            public bool AutoSrInstalled() { return false; }
            public string ForegroundExe() { return ""; }
        }

        // ---------- frame_sample ----------

        public static void FrameSample_ReturnsFpsAndGfxPower()
        {
            var rig = new Rig();
            rig.Adl.Fps = 58.5f;
            rig.Adl.Gpu = new GpuSensors { TempC = 45, GfxPowerW = 7 };
            var r = rig.Send("{\"id\":1,\"cmd\":\"frame_sample\"}");
            True(Ok(r), "frame_sample ok");
            var d = (Dictionary<string, object>)r["data"];
            Equal(true, d["supported"], "supported");
            Equal(58.5, Convert.ToDouble(d["fps"]), "fps");
            Equal(7, d["gpuPowerW"], "gpuPowerW");
            Equal(0, ((object[])d["errors"]).Length, "no errors");
            Equal(0, rig.Adl.Sets.Count, "no ADL write");
        }

        public static void FrameSample_Unsupported()
        {
            var rig = new Rig();
            rig.Adl.FrameSupported = false;
            var r = rig.Send("{\"id\":1,\"cmd\":\"frame_sample\"}");
            True(Ok(r), "frame_sample ok");
            var d = (Dictionary<string, object>)r["data"];
            Equal(false, d["supported"], "supported");
            True(d["fps"] == null, "fps null");
            var errors = (object[])d["errors"];
            Equal(1, errors.Length, "one error");
            True(((string)errors[0]).Contains("frame rate"), "error names the frame rate: " + errors[0]);
        }

        public static void FrameSample_ZeroPowerIsNull()
        {
            var rig = new Rig();
            rig.Adl.Gpu = new GpuSensors { GfxPowerW = 0 };
            var d = (Dictionary<string, object>)rig.Send("{\"id\":1,\"cmd\":\"frame_sample\"}")["data"];
            True(d["gpuPowerW"] == null, "0 W = not reported");
            Equal(60.0, Convert.ToDouble(d["fps"]), "fps still reported");
        }

        public static void FrameSample_RestartsMetricsAfterReset()
        {
            var rig = new Rig();
            rig.Send("{\"id\":1,\"cmd\":\"frame_sample\"}");
            rig.Send("{\"id\":2,\"cmd\":\"frame_sample\"}");
            Equal(1, rig.Adl.FrameStarts, "two samples start the metrics once");
            rig.Adl.Reset();
            var core = new TractionCore(rig.Adl, rig.Services, true, ms => { });
            core.HandleLine("{\"id\":3,\"cmd\":\"frame_sample\"}");
            Equal(2, rig.Adl.FrameStarts, "a restarted helper starts the metrics again");
        }

        // AdlHardware (real IAdl) on the fake control: start once, stop on dispose, missing entry points = unsupported.
        public static void AdlHardware_FrameRate()
        {
            var c = new FakeFpsControl { FpsValue = 77.5f };
            var hw = new AdlHardware(() => c);
            Equal(77.5, Convert.ToDouble(hw.GetFrameRate()), "fps");
            hw.GetFrameRate();
            Equal(1, c.Starts, "started once");
            True(hw.FrameRateSupported, "supported");
            c.FpsValue = float.PositiveInfinity;
            Equal(0.0, Convert.ToDouble(hw.GetFrameRate()), "+Infinity fps = 0");
            c.FpsValue = float.NaN;
            Equal(0.0, Convert.ToDouble(hw.GetFrameRate()), "NaN fps = 0");
            hw.Dispose();
            Equal(1, c.Stops, "stopped on dispose");

            var c2 = new FakeFpsControl { NoEntryPoint = true };
            var hw2 = new AdlHardware(() => c2);
            True(hw2.GetFrameRate() == null, "no entry point = null");
            True(!hw2.FrameRateSupported, "marked unsupported");
            True(hw2.Unavailable != null && hw2.Unavailable.Contains("frame rate"), "reason");
            hw2.Dispose();
            Equal(0, c2.Stops, "never started, never stopped");

            var c3 = new FakeFpsControl { StartResult = -1 };
            var hw3 = new AdlHardware(() => c3);
            True(hw3.GetFrameRate() == null, "start refused = null");
            True(hw3.FrameRateSupported, "still supported (retried next sample)");
        }

        // ---------- ASUS controller (mode, grip vibration) ----------

        private const string XboxProduct = "ROG Xbox Ally X RC73XA_RC73XA";

        // The report as it must reach the device: the bytes, then zeros up to the collection's feature length.
        private static byte[] Padded(int length, params byte[] head)
        {
            var b = new byte[length];
            Array.Copy(head, b, head.Length);
            return b;
        }

        private static string Hex(byte[] b) { return b == null ? "null" : BitConverter.ToString(b); }

        private static void WritesAre(FakeHidBus bus, string what, params byte[][] reports)
        {
            Equal(reports.Length, bus.Writes.Count, what + ": write count");
            for (int i = 0; i < reports.Length; i++)
            {
                Equal(FakeHidBus.MatchPath, bus.Writes[i].Key, what + ": write " + i + " path");
                Equal(Hex(reports[i]), Hex(bus.Writes[i].Value), what + ": write " + i + " bytes");
            }
        }

        public static void Controller_ModeBytes()
        {
            var rig = new Rig();
            var r = rig.Send("{\"id\":1,\"cmd\":\"set_controller_mode\",\"args\":{\"mode\":\"gamepad\"}}");
            True(Ok(r), "gamepad: " + Msg(r));
            Equal("gamepad", ((Dictionary<string, object>)r["data"])["mode"], "echoed mode");
            WritesAre(rig.Bus, "gamepad", Padded(64, 0x5A, 0xD1, 0x01, 0x01, 0x01));

            rig.Bus.Writes.Clear();
            r = rig.Send("{\"id\":2,\"cmd\":\"set_controller_mode\",\"args\":{\"mode\":\"desktop\"}}");
            True(Ok(r), "desktop: " + Msg(r));
            Equal("desktop", ((Dictionary<string, object>)r["data"])["mode"], "echoed mode");
            WritesAre(rig.Bus, "desktop", Padded(64, 0x5A, 0xD1, 0x01, 0x01, 0x03));

            // The padding follows the collection's own feature report length.
            var rig48 = new Rig();
            rig48.Bus = new FakeHidBus(48);
            rig48.Core.Hid = new AsusHid(rig48.Bus);
            True(Ok(rig48.Send("{\"id\":3,\"cmd\":\"set_controller_mode\",\"args\":{\"mode\":\"desktop\"}}")), "48-byte collection");
            WritesAre(rig48.Bus, "desktop on 48", Padded(48, 0x5A, 0xD1, 0x01, 0x01, 0x03));

            rig.Bus.Writes.Clear();
            rig.Bus.Fail = true;
            r = rig.Send("{\"id\":4,\"cmd\":\"set_controller_mode\",\"args\":{\"mode\":\"gamepad\"}}");
            True(!Ok(r) && Msg(r).Contains("feature write failed"), "write error passed on: " + Msg(r));
        }

        public static void Controller_VibrationBytes()
        {
            var rig = new Rig();
            var r = rig.Send("{\"id\":1,\"cmd\":\"set_vibration\",\"args\":{\"strength\":100}}");
            True(Ok(r), "on: " + Msg(r));
            Equal(100, ((Dictionary<string, object>)r["data"])["strength"], "echoed strength");
            WritesAre(rig.Bus, "non-Xbox on", Padded(64, 0x5A, 0xD1, 0x06, 0x02, 100, 100));

            rig.Bus.Writes.Clear();
            True(Ok(rig.Send("{\"id\":2,\"cmd\":\"set_vibration\",\"args\":{\"strength\":0}}")), "off");
            WritesAre(rig.Bus, "non-Xbox off", Padded(64, 0x5A, 0xD1, 0x06, 0x02, 0, 0));

            var x = new Rig();
            x.Core.ProductName = XboxProduct;
            True(Ok(x.Send("{\"id\":3,\"cmd\":\"set_vibration\",\"args\":{\"strength\":55}}")), "Xbox");
            WritesAre(x.Bus, "Xbox", Padded(64, 0x5A, 0xD1, 0x06, 0x02, 55, 55), Padded(64, 0x5A, 0xD1, 0x1C, 0x02, 55, 55));

            // A failed first write stops there and is reported.
            x.Bus.Writes.Clear();
            x.Bus.Fail = true;
            r = x.Send("{\"id\":4,\"cmd\":\"set_vibration\",\"args\":{\"strength\":100}}");
            True(!Ok(r) && Msg(r).Contains("feature write failed"), "write error passed on: " + Msg(r));
            Equal(1, x.Bus.Writes.Count, "no second write after a failure");
        }

        public static void ControllerHid_OnlyMatchingCollection()
        {
            SeqEqual(new[] { "1A30", "1854", "1869", "1866", "19B6", "1822", "1837", "1854", "184A", "183D", "8502", "1807",
                "17E0", "1ABE", "1B4C", "1B6E", "1B2C", "8854", "1CE7", "1CE6", "1BF2", "1BF3", "1CD7", "1CD8" },
                new List<int>(AsusHid.MAIN_AURA_PIDS).ConvertAll(p => p.ToString("X4")), "PIDs copied from G-Helper MAIN_AURA_PIDS");
            Equal(0x0B05, AsusHid.ASUS_ID, "vendor id");
            Equal((byte)0x5A, AsusHid.INPUT_ID, "input report id");

            var bus = new FakeHidBus();
            var hid = new AsusHid(bus);
            HidInfo info = hid.Find();
            True(info.Found, "found");
            Equal(0x1B4C, info.Pid, "pid");
            Equal(64, info.FeatureLength, "feature length");

            // Every command writes to the one matching collection only.
            var rig = new Rig();
            rig.Core.ProductName = XboxProduct;
            rig.Send("{\"id\":1,\"cmd\":\"set_controller_mode\",\"args\":{\"mode\":\"desktop\"}}");
            rig.Send("{\"id\":2,\"cmd\":\"set_vibration\",\"args\":{\"strength\":100}}");
            Equal(3, rig.Bus.Writes.Count, "three writes");
            foreach (var w in rig.Bus.Writes) Equal(FakeHidBus.MatchPath, w.Key, "written path");

            // controller_info: found, PID as hex, Xbox from the product name. It writes nothing.
            var r = rig.Send("{\"id\":3,\"cmd\":\"controller_info\"}");
            True(Ok(r), "info: " + Msg(r));
            var d = (Dictionary<string, object>)r["data"];
            Equal(true, d["found"], "found");
            Equal("0x1B4C", d["pid"], "pid");
            Equal(true, d["xbox"], "xbox");
            Equal(3, rig.Bus.Writes.Count, "info wrote nothing");
            var plain = new Rig();
            Equal(false, ((Dictionary<string, object>)plain.Send("{\"id\":4,\"cmd\":\"controller_info\"}")["data"])["xbox"], "non-Xbox");
            plain.Core.ProductName = null;
            Equal(false, ((Dictionary<string, object>)plain.Send("{\"id\":5,\"cmd\":\"controller_info\"}")["data"])["xbox"], "unknown product");

            // AsusHid itself refuses a report that is not a padded 0x5A report, before anything is sent.
            string err;
            True(!hid.SetFeature(new byte[] { 0x5A, 0xD1, 0x01, 0x01, 0x01 }, out err), "unpadded refused");
            True(!hid.SetFeature(Padded(64, 0x5D, 0xD1), out err), "other report id refused");
            True(!hid.SetFeature(null, out err), "null refused");
            Equal(0, bus.Writes.Count, "nothing sent");

            // Without the 0x5A collection nothing is found, even with the controller's other collections present.
            bus.Devices.RemoveAll(c => c.Path == FakeHidBus.MatchPath);
            True(!hid.Find().Found, "no 0x5A collection, not found");
            True(!hid.SetFeature(Padded(64, 0x5A, 0xD1, 0x01, 0x01, 0x01), out err), "write without a controller refused");
            Equal(0, bus.Writes.Count, "nothing sent to the other collections");
        }

        // The Win32 structs as the x64 Windows SDK lays them out. Nothing is opened or listed.
        public static void ControllerHid_Win32LayoutsX64()
        {
            Equal(8, IntPtr.Size, "tests run as x64, like the helper");
            SeqEqual(new[] { "32", "12", "64", "8" }, new List<int>(Win32HidBus.LayoutSizes()).ConvertAll(n => n.ToString()),
                "SP_DEVICE_INTERFACE_DATA, HIDD_ATTRIBUTES, HIDP_CAPS, detail cbSize");
        }

        public static void Controller_NotFoundRefused()
        {
            var rig = new Rig();
            rig.Bus.Devices.RemoveAll(c => c.Path == FakeHidBus.MatchPath);
            foreach (string line in new[] {
                "{\"id\":1,\"cmd\":\"set_controller_mode\",\"args\":{\"mode\":\"gamepad\"}}",
                "{\"id\":2,\"cmd\":\"set_vibration\",\"args\":{\"strength\":100}}" })
            {
                var r = rig.Send(line);
                Equal("Controller not found", Msg(r), "refused: " + line);
                True(!Ok(r), "not ok");
            }
            var info = rig.Send("{\"id\":3,\"cmd\":\"controller_info\"}");
            True(Ok(info), "info still answers");
            var d = (Dictionary<string, object>)info["data"];
            Equal(false, d["found"], "found");
            True(d["pid"] == null, "no pid");
            Equal(0, rig.Bus.Writes.Count, "nothing written");

            // No HID layer at all (Hid left null): refused as not available.
            var core = new TractionCore(new FakeAdl(), new FakeServices(), true, ms => { });
            foreach (string line in new[] {
                "{\"id\":1,\"cmd\":\"controller_info\"}",
                "{\"id\":2,\"cmd\":\"set_controller_mode\",\"args\":{\"mode\":\"gamepad\"}}",
                "{\"id\":3,\"cmd\":\"set_vibration\",\"args\":{\"strength\":0}}" })
            {
                var r = (Dictionary<string, object>)Json.DeserializeObject(core.HandleLine(line));
                True(!Ok(r) && Msg(r) == TractionCore.ControllerUnavailable, "not available: " + Msg(r));
            }
        }

        public static void Controller_InvalidArgsRefused()
        {
            var rig = new Rig();
            foreach (string m in new[] { "\"Gamepad\"", "\"mouse\"", "\"auto\"", "\"\"", "1", "3", "null", "true" })
                True(!Ok(rig.Send("{\"id\":1,\"cmd\":\"set_controller_mode\",\"args\":{\"mode\":" + m + "}}")), "mode " + m + " refused");
            True(!Ok(rig.Send("{\"id\":2,\"cmd\":\"set_controller_mode\"}")), "mode required");
            foreach (string v in new[] { "-1", "101", "255", "\"50\"", "1.5", "null", "true" })
                True(!Ok(rig.Send("{\"id\":3,\"cmd\":\"set_vibration\",\"args\":{\"strength\":" + v + "}}")), "strength " + v + " refused");
            True(!Ok(rig.Send("{\"id\":4,\"cmd\":\"set_vibration\"}")), "strength required");
            True(!Ok(rig.Send("{\"id\":5,\"cmd\":\"set_vibration\",\"args\":{\"strength\":50,\"x\":1}}")), "unknown arg refused");
            True(!Ok(rig.Send("{\"id\":6,\"cmd\":\"controller_info\",\"args\":{\"x\":1}}")), "info takes no args");
            Equal(0, rig.Bus.Lists, "refusals never reached the HID layer");
            Equal(0, rig.Bus.Writes.Count, "nothing written");
        }

        // ---------- button bindings (set_bindings) ----------

        // A zone report as the probe built it: 5A D1 02 zone 2C, then the four 11-byte slots at 5, 16, 27, 38.
        private static byte[] ZoneBytes(int zone, string s1, string s2, string s3, string s4)
        {
            var r = new byte[64];
            new byte[] { 0x5A, 0xD1, 0x02, (byte)zone, 0x2C }.CopyTo(r, 0);
            Bindings.Encode(s1).CopyTo(r, 5);
            Bindings.Encode(s2).CopyTo(r, 16);
            Bindings.Encode(s3).CopyTo(r, 27);
            Bindings.Encode(s4).CopyTo(r, 38);
            return r;
        }

        private static string SetLine(int id, string zone, string slots)
        {
            return "{\"id\":" + id + ",\"cmd\":\"set_bindings\",\"args\":{\"zone\":" + zone + ",\"slots\":" + slots + "}}";
        }

        // G-Helper's factory set, in the order the probe wrote it on the device (zone 8 first).
        private static byte[][] FactoryBytes(bool xbox)
        {
            var l = new List<byte[]>();
            var init = new byte[64];
            init[0] = 0x5A;
            System.Text.Encoding.ASCII.GetBytes("ASUS Tech.Inc.").CopyTo(init, 1);
            l.Add(init);
            l.Add(Padded(64, 0x5A, 0xD1, 0x0B, 0x01, 0x01));
            l.Add(Padded(64, 0x5A, 0xD1, 0x01, 0x01, 0x01));
            l.Add(ZoneBytes(8, "02-8E", "02-8E", "02-8F", "02-8F"));
            l.Add(ZoneBytes(1, "01-09", "05-19", "01-0A", "04-02-82-23"));
            l.Add(ZoneBytes(2, "01-0B", "04-04-8C-88-8A-05", "01-0C", "04-04-8C-88-8A-06"));
            l.Add(ZoneBytes(3, "01-07", "00-00", "01-08", "04-04-8C-88-8A-0C"));
            l.Add(ZoneBytes(4, "01-05", "00-00", "01-06", "00-00"));
            l.Add(ZoneBytes(5, "01-01", "00-00", "01-02", "00-00"));
            l.Add(ZoneBytes(6, "01-03", "04-03-82-88-1B", "01-04", "04-04-8C-88-8A-44"));
            l.Add(ZoneBytes(7, "01-11", "00-00", "01-12", "00-00"));
            l.Add(ZoneBytes(9, "01-0D", "00-00", "01-0E", "00-00"));
            l.Add(Padded(64, 0x5A, 0xD1, 0x0F, 0x20));
            l.Add(Padded(64, 0x5A, 0xD1, 0x04, 0x04, 0x00, 0x64, 0x00, 0x64));
            l.Add(Padded(64, 0x5A, 0xD1, 0x05, 0x04, 0x00, 0x64, 0x00, 0x64));
            l.Add(Padded(64, 0x5A, 0xD1, 0x06, 0x02, 0x64, 0x64));
            if (xbox) l.Add(Padded(64, 0x5A, 0xD1, 0x1C, 0x02, 0x64, 0x64));
            return l.ToArray();
        }

        // G-Helper DecodeBinding, as the probe's Code() ported it.
        public static void Bindings_EncodeSlots()
        {
            Equal("01-02-00-00-00-00-00-00-00-00-00", Hex(Bindings.Encode("01-02")), "gamepad button");
            Equal("02-00-5A-00-00-00-00-00-00-00-00", Hex(Bindings.Encode("02-5A")), "keyboard key");
            Equal("03-00-00-00-01-00-00-00-00-00-00", Hex(Bindings.Encode("03-01")), "mouse");
            Equal("04-00-00-00-00-03-82-88-1B-00-00", Hex(Bindings.Encode("04-03-82-88-1B")), "key combo");
            Equal("04-00-00-00-00-02-82-23-00-00-00", Hex(Bindings.Encode("04-02-82-23")), "two-key combo");
            Equal("05-00-00-19-00-00-00-00-00-00-00", Hex(Bindings.Encode("05-19")), "media key");
            Equal("00-00-00-00-00-00-00-00-00-00-00", Hex(Bindings.Encode("00-00")), "nothing");
            foreach (string code in Bindings.Allowed) Equal(11, Bindings.Encode(code).Length, "slot length " + code);
            True(Bindings.IsAllowed("02-8E") && Bindings.IsAllowed("02-8F"), "Shift codes allowed");
            True(Bindings.IsAllowed("02-88") && Bindings.IsAllowed("04-04-8C-88-8A-44"), "default codes allowed");
            True(!Bindings.IsAllowed("01-FF") && !Bindings.IsAllowed("01-02 ") && !Bindings.IsAllowed(null), "others refused");
        }

        public static void SetBindings_Zone8Bytes()
        {
            var rig = new Rig();
            var r = rig.Send(SetLine(1, "8", "[\"02-8E\",\"02-8E\",\"01-02\",\"02-8F\"]"));
            True(Ok(r), "ok: " + Msg(r));
            Equal(8, ((Dictionary<string, object>)r["data"])["zone"], "echoed zone");
            var expected = Padded(64, 0x5A, 0xD1, 0x02, 0x08, 0x2C);
            expected[5] = 0x02; expected[7] = 0x8E;     // left back button: Shift
            expected[16] = 0x02; expected[18] = 0x8E;   // its combo: Shift
            expected[27] = 0x01; expected[28] = 0x02;   // right back button: B
            expected[38] = 0x02; expected[40] = 0x8F;   // its combo: the factory Shift code (02 00 8F)
            WritesAre(rig.Bus, "zone 8", expected);
            // M5: present at the first poll and still present at poll 4 (2 s after the write) before ok
            Equal(5, rig.Pad.Calls, "checked before the write and at four polls after");
            SeqEqual(new[] { "500", "500", "500", "500" }, rig.Sleeps.ConvertAll(n => n.ToString()), "four 500 ms waits");
        }

        public static void SetBindings_RefusesBadInputWithoutWriting()
        {
            var rig = new Rig();
            string four = "[\"01-01\",\"00-00\",\"01-02\",\"00-00\"]";
            foreach (string line in new[] {
                SetLine(1, "5", "[\"01-01\",\"01-FF\",\"01-02\",\"00-00\"]"),
                SetLine(2, "0", four),
                SetLine(3, "10", four),
                SetLine(4, "-1", four),
                SetLine(5, "\"5\"", four),
                SetLine(6, "5.5", four),
                SetLine(7, "null", four),
                SetLine(8, "5", "[\"01-01\",\"00-00\",\"01-02\"]"),
                SetLine(9, "5", "[\"01-01\",\"00-00\",\"01-02\",\"00-00\",\"00-00\"]"),
                SetLine(10, "5", "[\"01-01\",1,\"01-02\",\"00-00\"]"),
                SetLine(11, "5", "[\"01-01\",null,\"01-02\",\"00-00\"]"),
                SetLine(12, "5", "\"01-01\""),
                SetLine(13, "5", "null"),
                SetLine(14, "5", "[\"01-01\",\"00-00\",\"01-02\",\"0-0\"]"),
                "{\"id\":15,\"cmd\":\"set_bindings\",\"args\":{\"zone\":5}}",
                "{\"id\":16,\"cmd\":\"set_bindings\",\"args\":{\"slots\":" + four + "}}",
                "{\"id\":17,\"cmd\":\"set_bindings\",\"args\":{\"zone\":5,\"slots\":" + four + ",\"x\":1}}",
                "{\"id\":19,\"cmd\":\"set_bindings\",\"args\":{\"zone\":5,\"slots\":" + four + ",\"watch\":1}}",
                "{\"id\":20,\"cmd\":\"set_bindings\",\"args\":{\"zone\":5,\"slots\":" + four + ",\"watch\":\"no\"}}",
                "{\"id\":21,\"cmd\":\"set_bindings\",\"args\":{\"zone\":5,\"slots\":" + four + ",\"watch\":null}}" })
            {
                var r = rig.Send(line);
                True(!Ok(r), "refused: " + line);
                True(Msg(r).StartsWith("Refused"), "says refused: " + Msg(r));
            }
            True(Msg(rig.Send(SetLine(18, "5", "[\"01-01\",\"01-FF\",\"01-02\",\"00-00\"]"))).Contains("01-FF"), "names the code");
            Equal(0, rig.Bus.Lists, "refusals never reached the HID layer");
            Equal(0, rig.Bus.Writes.Count, "nothing written");
            Equal(0, rig.Pad.Calls, "no gamepad check");
        }

        // Review Focus 4: the gamepad is gone after the write -> the factory set, in order, and the reset reply.
        public static void SetBindings_PadGone_WritesFactorySet()
        {
            foreach (bool xbox in new[] { false, true })
            {
                var rig = new Rig();
                if (xbox) rig.Core.ProductName = XboxProduct;
                rig.Pad.Answers.Enqueue(1);   // seen before the write
                rig.Pad.Then = 0;             // gone afterwards
                var r = rig.Send(SetLine(1, "5", "[\"01-01\",\"01-02\",\"01-02\",\"00-00\"]"));
                True(!Ok(r), "not ok");
                Equal("The controller stopped responding, so buttons were reset to the factory set.", Msg(r), "message");
                Equal(true, ((Dictionary<string, object>)r["data"])["reset"], "data.reset");
                var expected = new List<byte[]> { ZoneBytes(5, "01-01", "01-02", "01-02", "00-00") };
                expected.AddRange(FactoryBytes(xbox));
                WritesAre(rig.Bus, xbox ? "Xbox reset" : "reset", expected.ToArray());
                Equal(11, rig.Pad.Calls, "one check before, ten after");
                Equal(10, rig.Sleeps.Count, "ten waits");
                foreach (int ms in rig.Sleeps) Equal(500, ms, "500 ms each (5 s in all)");
            }
        }

        // A failed reset write does not stop the rest of the factory set, and the reply says the reset failed.
        public static void SetBindings_ResetWriteFails_TriesTheRest()
        {
            var rig = new Rig();
            rig.Pad.Answers.Enqueue(1);
            rig.Pad.Then = 0;
            var bus = new FailAfterBus(1);   // the zone report goes through, every reset write fails
            rig.Core.Hid = new AsusHid(bus);
            var r = rig.Send(SetLine(1, "5", "[\"01-01\",\"01-02\",\"01-02\",\"00-00\"]"));
            True(!Ok(r), "not ok");
            True(Msg(r).Contains("factory reset failed") && Msg(r).Contains("feature write failed"), "message: " + Msg(r));
            Equal(false, ((Dictionary<string, object>)r["data"])["reset"], "data.reset false");
            Equal(1 + FactoryBytes(false).Length, bus.Writes.Count, "every reset report was tried");
        }

        private class FailAfterBus : FakeHidBus
        {
            private readonly int okWrites;
            public FailAfterBus(int okWrites) { this.okWrites = okWrites; }
            public override bool SetFeature(string path, byte[] report, out string err)
            {
                base.SetFeature(path, report, out err);
                if (Writes.Count <= okWrites) return true;
                err = "feature write failed";
                return false;
            }
        }

        public static void SetBindings_PadBackOnLaterPoll_Ok()
        {
            var rig = new Rig();
            rig.Pad.Answers.Enqueue(1);
            rig.Pad.Answers.Enqueue(0);
            rig.Pad.Answers.Enqueue(0);
            rig.Pad.Then = 1;
            var r = rig.Send(SetLine(1, "5", "[\"01-01\",\"01-02\",\"01-02\",\"00-00\"]"));
            True(Ok(r), "ok: " + Msg(r));
            Equal(1, rig.Bus.Writes.Count, "only the zone report");
            Equal(7, rig.Pad.Calls, "seen on the third poll, confirmed on the sixth");
            Equal(6, rig.Sleeps.Count, "six waits");
        }

        // Without a gamepad to watch there is no safety net, so nothing is written.
        public static void SetBindings_NoPadBeforeWrite_Refused()
        {
            var rig = new Rig();
            rig.Pad.Then = 0;
            var r = rig.Send(SetLine(1, "5", "[\"01-01\",\"01-02\",\"01-02\",\"00-00\"]"));
            True(!Ok(r), "refused");
            Equal(TractionCore.PadNotSeenMessage, Msg(r), "message");
            Equal(0, rig.Bus.Writes.Count, "nothing written");
            Equal(0, rig.Sleeps.Count, "no wait");

            rig.Core.PadCheck = null;
            r = rig.Send(SetLine(2, "5", "[\"01-01\",\"01-02\",\"01-02\",\"00-00\"]"));
            True(!Ok(r) && Msg(r) == TractionCore.ControllerUnavailable, "no pad check: " + Msg(r));
            Equal(0, rig.Bus.Writes.Count, "nothing written");
        }

        public static void SetBindings_ControllerProblems()
        {
            var rig = new Rig();
            rig.Bus.Fail = true;
            var r = rig.Send(SetLine(1, "5", "[\"01-01\",\"01-02\",\"01-02\",\"00-00\"]"));
            True(!Ok(r) && Msg(r).Contains("feature write failed"), "write error passed on: " + Msg(r));
            Equal(1, rig.Bus.Writes.Count, "one attempt");

            var gone = new Rig();
            gone.Bus.Devices.RemoveAll(c => c.Path == FakeHidBus.MatchPath);
            r = gone.Send(SetLine(2, "5", "[\"01-01\",\"01-02\",\"01-02\",\"00-00\"]"));
            Equal("Controller not found", Msg(r), "not found");
            Equal(0, gone.Bus.Writes.Count, "nothing written");

            // The zone report is 49 bytes; a shorter collection is refused before anything is sent.
            var small = new Rig();
            small.Bus = new FakeHidBus(48);
            small.Core.Hid = new AsusHid(small.Bus);
            r = small.Send(SetLine(3, "5", "[\"01-01\",\"01-02\",\"01-02\",\"00-00\"]"));
            True(!Ok(r) && Msg(r).Contains("48 bytes"), "short report refused: " + Msg(r));
            Equal(0, small.Bus.Writes.Count, "nothing written");

            var not = new Rig(false);
            r = not.Send(SetLine(4, "5", "[\"01-01\",\"01-02\",\"01-02\",\"00-00\"]"));
            Equal(TractionCore.NotAllyMessage, Msg(r), "refused off the Ally");
            Equal(0, not.Bus.Writes.Count, "nothing written");
            Equal(0, not.Pad.Calls, "no gamepad check");
        }

        private static string WatchLine(int id, string zone, string slots, string watch)
        {
            return "{\"id\":" + id + ",\"cmd\":\"set_bindings\",\"args\":{\"zone\":" + zone + ",\"slots\":" + slots
                + ",\"watch\":" + watch + "}}";
        }

        private const string Z5 = "[\"01-01\",\"01-02\",\"01-02\",\"00-00\"]";

        // I2b: watch false (Desktop mode hides the XInput pad): no pad check, no polling, no factory reset.
        public static void SetBindings_WatchFalse_JustWrites()
        {
            var rig = new Rig();
            rig.Pad.Then = 0;   // Desktop mode: Windows sees no pad
            var r = rig.Send(WatchLine(1, "5", Z5, "false"));
            True(Ok(r), "ok: " + Msg(r));
            Equal(5, ((Dictionary<string, object>)r["data"])["zone"], "echoed zone");
            WritesAre(rig.Bus, "zone 5 only", ZoneBytes(5, "01-01", "01-02", "01-02", "00-00"));
            Equal(0, rig.Pad.Calls, "no gamepad check");
            Equal(0, rig.Sleeps.Count, "no wait");

            var failing = new Rig();
            failing.Pad.Then = 0;
            failing.Bus.Fail = true;
            r = failing.Send(WatchLine(2, "5", Z5, "false"));
            True(!Ok(r) && Msg(r).Contains("feature write failed"), "error passed on: " + Msg(r));
            True(r["data"] == null, "no reset data");
            Equal(1, failing.Bus.Writes.Count, "one attempt, no factory set");
            Equal(0, failing.Pad.Calls, "no gamepad check");

            var noPad = new Rig();
            noPad.Core.PadCheck = null;
            True(Ok(noPad.Send(WatchLine(3, "5", Z5, "false"))), "the pad check is not needed");

            var gone = new Rig();
            gone.Bus.Devices.RemoveAll(c => c.Path == FakeHidBus.MatchPath);
            Equal("Controller not found", Msg(gone.Send(WatchLine(4, "5", Z5, "false"))), "not found");
            Equal(0, gone.Bus.Writes.Count, "nothing written");
        }

        public static void SetBindings_WatchTrue_IsTheDefault()
        {
            var rig = new Rig();
            rig.Pad.Then = 0;
            var r = rig.Send(WatchLine(1, "5", Z5, "true"));
            Equal(TractionCore.PadNotSeenMessage, Msg(r), "watched: refused without a pad");
            Equal(0, rig.Bus.Writes.Count, "nothing written");
        }

        // M4: every XInput index present before the write must still be there; any missing one means the pad went.
        public static void SetBindings_PadIndexMissing_WritesFactorySet()
        {
            var rig = new Rig();
            rig.Pad.Answers.Enqueue(3);   // pads 0 and 1 before the write
            rig.Pad.Then = 1;             // pad 1 gone afterwards
            var r = rig.Send(SetLine(1, "5", Z5));
            True(!Ok(r), "not ok");
            Equal(Bindings.ResetMessage, Msg(r), "reset");
            Equal(true, ((Dictionary<string, object>)r["data"])["reset"], "data.reset");
            Equal(1 + FactoryBytes(false).Length, rig.Bus.Writes.Count, "zone then the factory set");

            var more = new Rig();
            more.Pad.Answers.Enqueue(1);   // pad 0 before
            more.Pad.Then = 3;             // pad 0 still there, another one appeared: fine
            True(Ok(more.Send(SetLine(2, "5", Z5))), "an extra pad is not a loss");
            Equal(1, more.Bus.Writes.Count, "only the zone report");

            var other = new Rig();
            other.Pad.Answers.Enqueue(2);  // only pad 1 present: still a pad to watch
            other.Pad.Then = 2;
            True(Ok(other.Send(SetLine(3, "5", Z5))), "pad 1 alone is watched");
        }

        // M5: a pad seen at a poll must still be seen 1.5 s later (four polls in a row) before ok; a gap starts over.
        public static void SetBindings_PadMustStayBeforeOk()
        {
            var rig = new Rig();
            rig.Pad.Answers.Enqueue(1);   // before
            foreach (int a in new[] { 1, 1, 1, 0, 1, 1, 1 }) rig.Pad.Answers.Enqueue(a);
            rig.Pad.Then = 1;
            var r = rig.Send(SetLine(1, "5", Z5));
            True(Ok(r), "ok after four in a row: " + Msg(r));
            Equal(9, rig.Pad.Calls, "polls 5-8 confirm after the gap at poll 4");
            Equal(1, rig.Bus.Writes.Count, "no factory set");

            var flicker = new Rig();
            flicker.Pad.Answers.Enqueue(1);
            foreach (int a in new[] { 1, 0, 1, 0, 1, 0, 1, 0, 1, 0 }) flicker.Pad.Answers.Enqueue(a);
            flicker.Pad.Then = 0;
            r = flicker.Send(SetLine(2, "5", Z5));
            Equal(Bindings.ResetMessage, Msg(r), "never steady: factory set");
            Equal(10, flicker.Sleeps.Count, "gone at poll 10: no more waiting");

            // first seen at the last regular poll: three more polls confirm it
            var late = new Rig();
            late.Pad.Answers.Enqueue(1);
            for (int i = 0; i < 9; i++) late.Pad.Answers.Enqueue(0);
            late.Pad.Then = 1;
            r = late.Send(SetLine(3, "5", Z5));
            True(Ok(r), "seen at poll 10, confirmed at 13: " + Msg(r));
            Equal(13, late.Sleeps.Count, "13 waits");

            // seen at poll 10, gone at 11: factory set
            var lost = new Rig();
            lost.Pad.Answers.Enqueue(1);
            for (int i = 0; i < 9; i++) lost.Pad.Answers.Enqueue(0);
            lost.Pad.Answers.Enqueue(1);
            lost.Pad.Then = 0;
            r = lost.Send(SetLine(4, "5", Z5));
            Equal(Bindings.ResetMessage, Msg(r), "lost again: factory set");
            Equal(11, lost.Sleeps.Count, "stopped at the gap after poll 10");
        }

        // M6: the factory reset looks for the controller up to 3 times, 1 s apart, before giving up.
        public static void SetBindings_ResetRetriesFind()
        {
            var rig = new Rig();
            rig.Pad.Answers.Enqueue(1);
            rig.Pad.Then = 0;
            var bus = new HidingBus(2, 2);   // after the zone write (Find + write), hidden for the next 2 lookups
            rig.Core.Hid = new AsusHid(bus);
            var r = rig.Send(SetLine(1, "5", Z5));
            Equal(Bindings.ResetMessage, Msg(r), "found on the third try: reset written");
            Equal(1 + FactoryBytes(false).Length, bus.Writes.Count, "zone then the whole factory set");
            var tail = rig.Sleeps.GetRange(rig.Sleeps.Count - 2, 2);
            SeqEqual(new[] { "1000", "1000" }, tail.ConvertAll(n => n.ToString()), "two 1 s waits between the tries");

            var never = new Rig();
            never.Pad.Answers.Enqueue(1);
            never.Pad.Then = 0;
            var bus2 = new HidingBus(2, 100);
            never.Core.Hid = new AsusHid(bus2);
            r = never.Send(SetLine(2, "5", Z5));
            True(!Ok(r) && Msg(r).Contains("factory reset failed") && Msg(r).Contains("Controller not found"), "gave up: " + Msg(r));
            Equal(false, ((Dictionary<string, object>)r["data"])["reset"], "data.reset false");
            Equal(1, bus2.Writes.Count, "only the zone report");
            Equal(2 + 3, bus2.Lists, "zone Find and write, then three tries");
            Equal(10 + 2, never.Sleeps.Count, "ten polls, two retry waits");

            // the zone write itself does not retry: a missing controller is refused at once
            var plain = new Rig();
            var bus3 = new HidingBus(0, 100);
            plain.Core.Hid = new AsusHid(bus3);
            Equal("Controller not found", Msg(plain.Send(SetLine(3, "5", Z5))), "not found");
            Equal(1, bus3.Lists, "one lookup");
        }

        // Hides the controller collection for `count` List calls after the first `after` ones.
        private class HidingBus : FakeHidBus
        {
            private readonly int after, count;
            public HidingBus(int after, int count) { this.after = after; this.count = count; }
            public override List<HidCollection> List()
            {
                var l = base.List();
                if (Lists > after && Lists <= after + count) l.RemoveAll(c => c.Path == MatchPath);
                return l;
            }
        }

        // ---------- touchscreen and foreground ----------

        public static void Touchscreen_SetReturnsAtOnce()
        {
            var rig = new Rig();
            var r = rig.Send("{\"id\":1,\"cmd\":\"set_touchscreen\",\"args\":{\"enabled\":false}}");
            True(Ok(r), "set accepted: " + Msg(r));
            Equal(false, ((Dictionary<string, object>)r["data"])["enabled"], "echo");
            SeqEqual(new[] { "False" }, rig.Sys.TouchSets.ConvertAll(b => b.ToString()), "started once, disabling");
            Equal(0, rig.Sys.TouchReads, "set never waits on a read");
            // a second change while the first runs is refused
            var r2 = rig.Send("{\"id\":2,\"cmd\":\"set_touchscreen\",\"args\":{\"enabled\":true}}");
            True(!Ok(r2) && Msg(r2).Contains("already running"), "busy refused: " + Msg(r2));
            Equal(1, rig.Sys.TouchSets.Count, "second not started");
            // arguments are checked
            True(!Ok(rig.Send("{\"id\":3,\"cmd\":\"set_touchscreen\",\"args\":{\"enabled\":1}}")), "enabled must be a boolean");
            True(!Ok(rig.Send("{\"id\":4,\"cmd\":\"set_touchscreen\"}")), "enabled required");
            rig.Sys.TouchBusy = false;
            rig.Sys.TouchStartFails = true;
            var r3 = rig.Send("{\"id\":5,\"cmd\":\"set_touchscreen\",\"args\":{\"enabled\":true}}");
            True(!Ok(r3) && Msg(r3) == "Could not start PowerShell.", "start failure reported: " + Msg(r3));
        }

        public static void Touchscreen_GetReportsState()
        {
            var rig = new Rig();
            var r = rig.Send("{\"id\":1,\"cmd\":\"get_touchscreen\"}");
            True(Ok(r), Msg(r));
            var d = (Dictionary<string, object>)r["data"];
            Equal(true, d["found"], "found");
            Equal(true, d["enabled"], "enabled");
            Equal(@"HID\NVTK0603&COL01\5&1234&0&0000", d["instanceId"], "instance id");
            rig.Sys.Touch = new TouchInfo { Found = true, Enabled = false, InstanceId = "x" };
            Equal(false, ((Dictionary<string, object>)rig.Send("{\"id\":2,\"cmd\":\"get_touchscreen\"}")["data"])["enabled"], "disabled");
            rig.Sys.Touch = new TouchInfo { Error = "PowerShell did not answer in 5 seconds." };
            var e = rig.Send("{\"id\":3,\"cmd\":\"get_touchscreen\"}");
            True(!Ok(e) && Msg(e) == "PowerShell did not answer in 5 seconds.", "read timeout reported: " + Msg(e));
        }

        public static void Touchscreen_PickDevice_PresentOnlyFixedText()
        {
            string cmd = SystemControls.PickDevice;
            True(cmd.StartsWith("Get-PnpDevice -PresentOnly -FriendlyName '*touch*screen*' |"), "present devices only: " + cmd);
            True(cmd.IndexOf("{0}") < 0 && cmd.IndexOf('"') < 0, "fixed text, no placeholder for client input");
        }

        public static void Touchscreen_NotFound()
        {
            var rig = new Rig();
            rig.Sys.Touch = new TouchInfo { Found = false };
            var r = rig.Send("{\"id\":1,\"cmd\":\"get_touchscreen\"}");
            True(Ok(r), "not found is a normal answer: " + Msg(r));
            var d = (Dictionary<string, object>)r["data"];
            Equal(false, d["found"], "found");
            Equal(false, d["enabled"], "enabled");
            Equal(null, d["instanceId"], "no instance id");
        }

        public static void System_NotAvailableWithoutSystemControls()
        {
            var rig = new Rig();
            rig.Core.SystemControls = null;
            foreach (string c in new[] { "get_touchscreen", "foreground" })
            {
                var r = rig.Send("{\"id\":1,\"cmd\":\"" + c + "\"}");
                True(!Ok(r) && Msg(r) == TractionCore.SystemUnavailable, c + ": " + Msg(r));
            }
            var s = rig.Send("{\"id\":2,\"cmd\":\"set_touchscreen\",\"args\":{\"enabled\":true}}");
            True(!Ok(s) && Msg(s) == TractionCore.SystemUnavailable, "set_touchscreen: " + Msg(s));
        }

        public static void Foreground_Lowercase()
        {
            var rig = new Rig();
            rig.Sys.Foreground = "steam.exe";
            Equal("steam.exe", ((Dictionary<string, object>)rig.Send("{\"id\":1,\"cmd\":\"foreground\"}")["data"])["exe"], "exe");
            rig.Sys.Foreground = "Steam.EXE";
            Equal("steam.exe", ((Dictionary<string, object>)rig.Send("{\"id\":2,\"cmd\":\"foreground\"}")["data"])["exe"], "lowercased by the protocol too");
            rig.Sys.Foreground = null;
            Equal("", ((Dictionary<string, object>)rig.Send("{\"id\":3,\"cmd\":\"foreground\"}")["data"])["exe"], "none gives empty");
        }

        public static void Foreground_AllowedOffAlly()
        {
            var rig = new Rig(false);
            rig.Sys.Foreground = "game.exe";
            True(Ok(rig.Send("{\"id\":1,\"cmd\":\"foreground\"}")), "read");
            True(Ok(rig.Send("{\"id\":2,\"cmd\":\"get_touchscreen\"}")), "read");
            True(Ok(rig.Send("{\"id\":3,\"cmd\":\"controller_info\"}")), "read");
            True(!Ok(rig.Send("{\"id\":4,\"cmd\":\"set_touchscreen\",\"args\":{\"enabled\":false}}")), "write refused");
            Equal(0, rig.Sys.TouchSets.Count, "no touch change");
        }

        public static void NotAlly_RefusesAllButReadAllowList()
        {
            SeqEqual(new[] { "hello", "frame_sample", "foreground", "armoury_state", "controller_info", "get_touchscreen" },
                new List<string>(TractionCore.ReadCommands), "read allow-list");
            var rig = new Rig(false);
            int n = 0, refused = 0;
            foreach (string cmd in TractionCore.CommandNames)
            {
                var r = rig.Send("{\"id\":" + (++n) + ",\"cmd\":\"" + cmd + "\"}");
                bool read = Array.IndexOf(TractionCore.ReadCommands, cmd) >= 0;
                if (read) True(Msg(r) != TractionCore.NotAllyMessage, cmd + " is a read and must not be refused as non-Ally");
                else { True(!Ok(r) && Msg(r) == TractionCore.NotAllyMessage, cmd + " refused: " + Msg(r)); refused++; }
            }
            Equal(7, refused, "every non-read command refused");
            Equal(0, rig.Bus.Writes.Count, "no HID write");
            Equal(0, rig.Adl.Sets.Count, "no ADL write");
            Equal(0, rig.Services.Changes().Count, "no service change");
            Equal(0, rig.Sys.TouchSets.Count, "no touch change");
        }

        // ---------- Armoury Crate button (ButtonActions, ButtonListener, set_button_action) ----------

        private static readonly byte[] Ec = { 0x5A, 0xEC };

        private class ListenRig
        {
            public FakeReportSource Source = new FakeReportSource();
            public FakeInputSender Sender = new FakeInputSender();
            public DateTime Now = new DateTime(2026, 10, 25, 12, 0, 0, DateTimeKind.Utc);
            private readonly List<int> waits = new List<int>();
            public ButtonListener Listener;

            public ListenRig()
            {
                Listener = new ButtonListener(Source, Sender, () => Now, ms => { lock (waits) waits.Add(ms); });
            }

            public List<int> Waits { get { lock (waits) return new List<int>(waits); } }
        }

        // Polls cond every 10 ms for up to ms; true when it held.
        private static bool WaitUntil(Func<bool> cond, int ms)
        {
            DateTime end = DateTime.UtcNow.AddMilliseconds(ms);
            while (DateTime.UtcNow < end)
            {
                if (cond()) return true;
                Thread.Sleep(10);
            }
            return cond();
        }

        public static void ButtonActions_IdsMatchPlan()
        {
            SeqEqual(new[] { "nothing", "mouse_left", "mouse_right", "mouse_middle", "scroll_up", "scroll_down", "esc",
                "enter", "tab", "backspace", "space", "up", "down", "left", "right", "page_up", "page_down", "win",
                "show_desktop", "screenshot", "task_manager", "close_window", "alt_tab", "win_tab", "volume_up",
                "volume_down" }, ButtonActions.Ids, "action ids");
            foreach (string id in ButtonActions.Ids)
            {
                True(ButtonActions.Steps(id) != null, id + " has steps");
                if (id != "nothing") True(ButtonActions.Steps(id).Count > 0, id + " sends something");
            }
            SeqEqual(new[] { "down 0x11", "down 0x10", "down 0x1B", "up 0x1B", "up 0x10", "up 0x11" },
                ButtonActions.Describe("task_manager"), "task manager");
            SeqEqual(new[] { "down 0x12", "down 0x73", "up 0x73", "up 0x12" }, ButtonActions.Describe("close_window"), "Alt+F4");
            SeqEqual(new[] { "down 0x5B", "down 0x44", "up 0x44", "up 0x5B" }, ButtonActions.Describe("show_desktop"), "Win+D");
            SeqEqual(new[] { "down 0xAF", "up 0xAF" }, ButtonActions.Describe("volume_up"), "volume up");
            SeqEqual(new[] { "mouse left down", "mouse left up" }, ButtonActions.Describe("mouse_left"), "left click");
            SeqEqual(new[] { "mouse right down", "mouse right up" }, ButtonActions.Describe("mouse_right"), "right click");
            SeqEqual(new[] { "mouse middle down", "mouse middle up" }, ButtonActions.Describe("mouse_middle"), "middle click");
        }

        public static void ButtonActions_Screenshot()
        {
            SeqEqual(new[] { "down 0x5B", "down 0x10", "down 0x53", "up 0x53", "up 0x10", "up 0x5B" },
                ButtonActions.Describe("screenshot"), "Win+Shift+S");
        }

        public static void ButtonActions_ArrowIsExtended()
        {
            IList<InputStep> up = ButtonActions.Steps("up");
            Equal(2, up.Count, "down and up");
            Equal((ushort)0x26, up[0].Vk, "vk");
            True(!up[0].Up && up[1].Up, "down then up");
            True(up[0].Extended && up[1].Extended, "arrows are extended keys");
            True(!up[0].Mouse, "a key, not the mouse");
            True(ButtonActions.Steps("page_down")[0].Extended, "Page Down is extended");
            IList<InputStep> enter = ButtonActions.Steps("enter");
            Equal((ushort)0x0D, enter[0].Vk, "enter vk");
            True(!enter[0].Extended && !enter[1].Extended, "Enter is not extended");
        }

        public static void ButtonActions_ScrollDown()
        {
            SeqEqual(new[] { "wheel -120" }, ButtonActions.Describe("scroll_down"), "scroll down");
            SeqEqual(new[] { "wheel 120" }, ButtonActions.Describe("scroll_up"), "scroll up");
            Equal(0, ButtonActions.Steps("nothing").Count, "nothing sends nothing");
            True(ButtonActions.Steps("a") == null, "a gamepad button is not an action");
            True(ButtonActions.Steps("touch_keyboard") == null, "no touch keyboard");
            True(ButtonActions.Steps(null) == null, "null id");
            True(ButtonActions.Describe("a") == null, "unknown id described as null");
        }

        public static void InputSender_Win32LayoutX64()
        {
            Equal(40, Win32InputSender.InputSize(), "INPUT is 40 bytes on x64");
        }

        public static void Listener_OnlyEcFires()
        {
            var rig = new ListenRig();
            try
            {
                rig.Listener.SetAction("enter");
                True(rig.Listener.Handle(Ec), "5A EC fires");
                Equal(1, rig.Sender.Count, "one send");
                Equal("down 0x0D, up 0x0D", rig.Sender.Sends[0], "the chosen action");
                rig.Now = rig.Now.AddSeconds(5);
                True(!rig.Listener.Handle(new byte[] { 0x5A, 0xA6 }), "5A A6 ignored");
                True(!rig.Listener.Handle(new byte[] { 0x5A, 0x00 }), "5A 00 ignored");
                True(!rig.Listener.Handle(new byte[] { 0x5D, 0xEC }), "5D EC ignored");
                True(!rig.Listener.Handle(new byte[] { 0x5A }), "short report ignored");
                True(!rig.Listener.Handle(new byte[0]), "empty report ignored");
                True(!rig.Listener.Handle(null), "null report ignored");
                Equal(1, rig.Sender.Count, "still one send");
                True(rig.Listener.Handle(new byte[] { 0x5A, 0xEC, 0x00, 0x00 }), "5A EC with padding fires");
            }
            finally { rig.Listener.SetAction("nothing"); }
        }

        public static void Listener_SenderErrorCaught()
        {
            var rig = new ListenRig();
            rig.Sender.Throw = true;
            try
            {
                rig.Listener.SetAction("esc");
                True(rig.Listener.Handle(Ec), "fired even though the send failed");
                rig.Now = rig.Now.AddSeconds(1);
                rig.Source.Push(Ec);
                True(WaitUntil(() => rig.Sender.Count == 2, 3000), "the reader thread sent the pushed press");
                True(rig.Listener.Running, "a send failure does not end the reader");
            }
            finally { rig.Listener.SetAction("nothing"); }
        }

        public static void Listener_Bounce()
        {
            var rig = new ListenRig();
            try
            {
                rig.Listener.SetAction("space");
                DateTime t = rig.Now;
                True(rig.Listener.Handle(Ec), "first press fires");
                rig.Now = t.AddSeconds(0.2);
                True(!rig.Listener.Handle(Ec), "a repeat 0.2 s later is ignored");
                rig.Now = t.AddSeconds(0.7);
                True(rig.Listener.Handle(Ec), "0.7 s later fires");
                rig.Now = t.AddSeconds(6.0);
                True(rig.Listener.Handle(Ec), "the release report after a long hold fires (known limit)");
                Equal(3, rig.Sender.Count, "three sends");
            }
            finally { rig.Listener.SetAction("nothing"); }
        }

        public static void Listener_NothingStops()
        {
            var rig = new ListenRig();
            Equal("nothing", rig.Listener.Action, "starts as nothing");
            True(!rig.Listener.Running, "no reader before an action");
            rig.Listener.SetAction("task_manager");
            True(rig.Listener.Running, "reader running");
            True(WaitUntil(() => rig.Source.IsOpen, 2000), "collection opened");
            rig.Listener.SetAction("task_manager");
            Equal(1, rig.Listener.Opens, "the same action again is a no-op");
            rig.Listener.SetAction("nothing");
            True(WaitUntil(() => !rig.Listener.Running, 1000), "reader ended within 1 s");
            True(!rig.Source.IsOpen && rig.Source.Closes >= 1, "collection closed");
            Equal("nothing", rig.Listener.Action, "action");
            True(!rig.Listener.Handle(Ec), "a later press does nothing");
            rig.Source.Push(Ec);
            Thread.Sleep(50);
            Equal(0, rig.Sender.Count, "nothing sent");
            int opens = rig.Source.OpenCalls;
            Thread.Sleep(50);
            Equal(opens, rig.Source.OpenCalls, "no reopen after nothing");
        }

        public static void Listener_ReopensAfterReadFailure()
        {
            var rig = new ListenRig();
            rig.Source.OpenResults.Enqueue(true);
            rig.Source.OpenResults.Enqueue(false);
            rig.Source.Push(new IOException("The device is not connected."));
            rig.Source.Push(Ec);
            try
            {
                rig.Listener.SetAction("win");
                True(WaitUntil(() => rig.Sender.Count == 1, 3000), "the press after the reopen fired");
                Equal("down 0x5B, up 0x5B", rig.Sender.Sends[0], "the chosen action");
                Equal(2, rig.Listener.Opens, "opened twice (the failed open does not count)");
                Equal(3, rig.Source.OpenCalls, "three open attempts");
                True(rig.Waits.Contains(2000), "waited 2000 ms before reopening");
                True(rig.Waits.TrueForAll(ms => ms == 2000), "every wait is 2000 ms: " + string.Join(",", rig.Waits));
                Equal(2, rig.Waits.Count, "one wait after the read failure, one after the failed open");
                True(rig.Listener.Running, "still running");
            }
            finally { rig.Listener.SetAction("nothing"); }
            True(WaitUntil(() => !rig.Listener.Running, 1000), "stopped");
        }

        public static void ButtonActions_WithScanFillsScanCode()
        {
            var asked = new List<uint>();
            Func<uint, uint> map = vk =>
            {
                asked.Add(vk);
                switch (vk)
                {
                    case 0x0D: return 0x1C;      // Enter
                    case 0x5B: return 0xE05B;    // left Windows key (E0)
                    case 0x26: return 0xE048;    // Up (E0)
                    case 0xAF: return 0xE030;    // Volume Up (E0)
                    case 0x13: return 0xE11D;    // Pause (E1, not E0)
                }
                return 0;
            };
            InputStep enter = ButtonActions.WithScan(ButtonActions.Steps("enter")[0], map);
            Equal((ushort)0x0D, enter.Vk, "the virtual key stays");
            Equal((ushort)0x1C, enter.Scan, "Enter scan code");
            True(!enter.Extended, "Enter is not extended");
            InputStep win = ButtonActions.WithScan(ButtonActions.Steps("win")[1], map);
            Equal((ushort)0x5B, win.Scan, "Win scan code without the E0 byte");
            True(win.Extended && win.Up, "E0 sets the extended flag; up stays up");
            InputStep vol = ButtonActions.WithScan(ButtonActions.Steps("volume_up")[0], map);
            True(vol.Extended && vol.Scan == 0x30, "Volume Up: E0 30, extended");
            InputStep up = ButtonActions.WithScan(ButtonActions.Steps("up")[0], v => 0x48);
            True(up.Extended && up.Scan == 0x48, "an arrow stays extended even when the mapper gives no E0");
            InputStep pause = ButtonActions.WithScan(new InputStep { Vk = 0x13 }, map);
            True(!pause.Extended && pause.Scan == 0x1D, "an E1 prefix is not the extended flag");
            InputStep none = ButtonActions.WithScan(new InputStep { Vk = 0x07 }, map);
            True(!none.Extended && none.Scan == 0, "no scan code: 0, not extended");
            int before = asked.Count;
            InputStep click = ButtonActions.WithScan(ButtonActions.Steps("mouse_left")[0], map);
            Equal(before, asked.Count, "a mouse step is not mapped");
            True(click.Mouse && click.Scan == 0 && !click.Extended, "a mouse step is unchanged");
        }

        public static void Listener_EmptyReadIsAFailedRead()
        {
            var rig = new ListenRig();
            rig.Source.Push(new byte[0]);
            rig.Source.Push(Ec);
            try
            {
                rig.Listener.SetAction("esc");
                True(WaitUntil(() => rig.Sender.Count == 1, 3000), "the press after the reopen fired");
                Equal(2, rig.Listener.Opens, "an empty read closes and reopens");
                True(rig.Source.Closes >= 1, "closed after the empty read");
                True(rig.Waits.Count == 1 && rig.Waits[0] == 2000, "one 2000 ms wait before reopening: " + string.Join(",", rig.Waits));
                True(rig.Listener.LastError.Contains("empty"), "last error says empty: " + rig.Listener.LastError);
            }
            finally { rig.Listener.SetAction("nothing"); }
        }

        public static void Listener_OpenAndLastError()
        {
            var rig = new ListenRig();
            Equal("", rig.Listener.LastError, "no error at first");
            True(!rig.Listener.IsOpen, "not open before an action");
            rig.Source.OpenResults.Enqueue(false);
            try
            {
                rig.Listener.SetAction("esc");
                True(WaitUntil(() => rig.Listener.IsOpen, 3000), "open after the retry");
                True(rig.Listener.LastError.Contains("open"), "the failed open is the last error: " + rig.Listener.LastError);
                rig.Source.Push(new IOException("The device is not connected."));
                True(WaitUntil(() => rig.Listener.LastError.Contains("not connected"), 3000),
                    "the read failure is the last error: " + rig.Listener.LastError);
                True(WaitUntil(() => rig.Listener.IsOpen, 3000), "open again after the reopen");
                rig.Sender.Throw = true;
                rig.Source.Push(Ec);
                True(WaitUntil(() => rig.Listener.LastError.Contains("SendInput failed"), 3000),
                    "the send failure is the last error: " + rig.Listener.LastError);
            }
            finally { rig.Listener.SetAction("nothing"); }
            True(!rig.Listener.IsOpen, "not open after nothing");
        }

        private static ListenRig AttachListener(Rig rig)
        {
            var l = new ListenRig();
            rig.Core.ButtonListener = l.Listener;
            return l;
        }

        public static void SetButtonAction_RefusesUnknown()
        {
            var rig = new Rig();
            ListenRig l = AttachListener(rig);
            var r = rig.Send("{\"id\":1,\"cmd\":\"set_button_action\",\"args\":{\"action\":\"a\"}}");
            True(!Ok(r), "unknown refused");
            Equal("Refused: unknown button action 'a'.", Msg(r), "message");
            r = rig.Send("{\"id\":2,\"cmd\":\"set_button_action\",\"args\":{\"action\":\"touch_keyboard\"}}");
            Equal("Refused: unknown button action 'touch_keyboard'.", Msg(r), "touch keyboard refused");
            r = rig.Send("{\"id\":3,\"cmd\":\"set_button_action\",\"args\":{\"action\":5}}");
            True(!Ok(r) && Msg(r).StartsWith("Refused: unknown button action"), "non-text refused: " + Msg(r));
            r = rig.Send("{\"id\":4,\"cmd\":\"set_button_action\",\"args\":{}}");
            True(!Ok(r) && Msg(r) == "Refused: 'action' is required.", "missing refused: " + Msg(r));
            r = rig.Send("{\"id\":5,\"cmd\":\"set_button_action\",\"args\":{\"action\":\"esc\",\"x\":1}}");
            True(!Ok(r), "unknown arg refused");
            Equal("nothing", l.Listener.Action, "action unchanged");
            True(!l.Listener.Running, "no reader started");
            Equal(0, l.Source.OpenCalls, "collection never opened");

            var bare = new Rig();
            r = bare.Send("{\"id\":6,\"cmd\":\"set_button_action\",\"args\":{\"action\":\"esc\"}}");
            True(!Ok(r), "no listener refused");
            Equal(TractionCore.ControllerUnavailable, Msg(r), "no listener message");
        }

        public static void SetButtonAction_ReplyHasActionAndRunning()
        {
            var rig = new Rig();
            ListenRig l = AttachListener(rig);
            try
            {
                var r = rig.Send("{\"id\":1,\"cmd\":\"set_button_action\",\"args\":{\"action\":\"screenshot\"}}");
                True(Ok(r), "ok: " + Msg(r));
                var d = (Dictionary<string, object>)r["data"];
                Equal("screenshot", d["action"], "action");
                Equal(true, d["running"], "running");
                True(WaitUntil(() => l.Source.IsOpen, 2000), "collection opened");
                r = rig.Send("{\"id\":2,\"cmd\":\"set_button_action\",\"args\":{\"action\":\"screenshot\"}}");
                d = (Dictionary<string, object>)r["data"];
                True(Ok(r) && (bool)d["running"], "the same action again still running");
                Equal(1, l.Listener.Opens, "the same action again is a no-op");
                r = rig.Send("{\"id\":3,\"cmd\":\"set_button_action\",\"args\":{\"action\":\"alt_tab\"}}");
                d = (Dictionary<string, object>)r["data"];
                True(Ok(r) && (string)d["action"] == "alt_tab" && (bool)d["running"], "another action");
                l.Now = l.Now.AddSeconds(1);
                True(l.Listener.Handle(Ec), "fires");
                Equal("down 0x12, down 0x09, up 0x09, up 0x12", l.Sender.Sends[0], "the new action runs");
                r = rig.Send("{\"id\":4,\"cmd\":\"set_button_action\",\"args\":{\"action\":\"nothing\"}}");
                d = (Dictionary<string, object>)r["data"];
                True(Ok(r), "nothing ok");
                Equal("nothing", d["action"], "action nothing");
                Equal(false, d["running"], "not running");
                Equal(0, rig.Bus.Writes.Count, "nothing written to the controller");
            }
            finally { l.Listener.SetAction("nothing"); }
        }

        public static void SetButtonAction_ReplyHasOpenAndLastError()
        {
            var rig = new Rig();
            ListenRig l = AttachListener(rig);
            try
            {
                var r = rig.Send("{\"id\":1,\"cmd\":\"set_button_action\",\"args\":{\"action\":\"nothing\"}}");
                var d = (Dictionary<string, object>)r["data"];
                Equal(false, d["open"], "not open with nothing");
                Equal("", d["last_error"], "no error yet");
                l.Source.OpenResults.Enqueue(false);
                rig.Send("{\"id\":2,\"cmd\":\"set_button_action\",\"args\":{\"action\":\"esc\"}}");
                True(WaitUntil(() => l.Listener.IsOpen, 3000), "opened after the retry");
                r = rig.Send("{\"id\":3,\"cmd\":\"set_button_action\",\"args\":{\"action\":\"esc\"}}");
                d = (Dictionary<string, object>)r["data"];
                Equal(true, d["open"], "open");
                True(((string)d["last_error"]).Contains("open"), "last error: " + d["last_error"]);
            }
            finally { l.Listener.SetAction("nothing"); }
        }

        public static void SetButtonAction_NotAllyRefused()
        {
            var rig = new Rig(false);
            ListenRig l = AttachListener(rig);
            var r = rig.Send("{\"id\":1,\"cmd\":\"set_button_action\",\"args\":{\"action\":\"esc\"}}");
            True(!Ok(r), "refused off the Ally");
            Equal(TractionCore.NotAllyMessage, Msg(r), "message");
            True(Array.IndexOf(TractionCore.ReadCommands, "set_button_action") < 0, "not a read command");
            Equal("nothing", l.Listener.Action, "action unchanged");
            True(!l.Listener.Running, "no reader");
        }

        // ---------- Armoury Crate ----------

        // G-Helper app/Helpers/AsusService.cs lines 10-25 (services) and 29-33 (servicesAC), commit in helper\GHELPER_COMMIT;
        // "AsusPTPService" is commented out upstream (line 27) and stays out.
        public static void Armoury_ListsMatchGHelper()
        {
            SeqEqual(new[] { "ArmouryCrateControlInterface", "ArmouryCrateProArtService", "AsHidService", "ASUSOptimization",
                "AsusAppService", "ASUSLinkNear", "ASUSLinkRemote", "ASUSSoftwareManager", "ASUSLiveUpdateAgent", "ASUSSwitch",
                "ASUSSystemAnalysis", "ASUSSystemDiagnosis", "ASUSXGMobileService", "AsusCertService" },
                ArmouryServices.Services, "services");
            SeqEqual(new[] { "ArmouryCrateSEService", "ArmouryCrateService", "LightingService" }, ArmouryServices.ServicesAC, "servicesAC");
            Equal(17, ArmouryServices.All.Count, "all");
            True(!ArmouryServices.IsListed("AsusPTPService"), "AsusPTPService not listed");
            True(!ArmouryServices.IsListed("armourycrateseservice"), "names are exact");
        }

        // State before Armoury is replaced: four listed services running, one stopped, one unrelated service.
        private static Rig ArmouryRig()
        {
            var rig = new Rig();
            var s = rig.Services;
            s.Types["ArmouryCrateControlInterface"] = "Automatic"; s.RunningNames.Add("ArmouryCrateControlInterface");
            s.Types["ASUSOptimization"] = "Automatic";              // installed but stopped
            s.Types["AsusAppService"] = "Automatic"; s.RunningNames.Add("AsusAppService");
            s.Types["ArmouryCrateSEService"] = "AutomaticDelayedStart"; s.RunningNames.Add("ArmouryCrateSEService");
            s.Types["LightingService"] = "Manual"; s.RunningNames.Add("LightingService");
            s.Types["Spooler"] = "Automatic"; s.RunningNames.Add("Spooler");
            return rig;
        }

        private static string Snapshot(FakeServices s)
        {
            var names = new List<string>(s.Types.Keys);
            names.Sort(StringComparer.Ordinal);
            var parts = new List<string>();
            foreach (string n in names) parts.Add(n + "=" + s.Types[n] + (s.RunningNames.Contains(n) ? "+run" : ""));
            return string.Join(", ", parts);
        }

        public static void Armoury_State_Shape()
        {
            var rig = ArmouryRig();
            var r = rig.Send("{\"id\":1,\"cmd\":\"armoury_state\"}");
            True(Ok(r), "ok: " + Msg(r));
            var d = (Dictionary<string, object>)r["data"];
            SeqEqual(new[] { "installed", "startTypes", "running" }, new List<string>(d.Keys), "keys");
            Equal(true, d["installed"], "installed");
            var types = (Dictionary<string, object>)d["startTypes"];
            Equal(5, types.Count, "listed services only");
            Equal("AutomaticDelayedStart", types["ArmouryCrateSEService"], "delayed start kept");
            True(!types.ContainsKey("Spooler"), "unrelated service not reported");
            Equal("ArmouryCrateControlInterface,AsusAppService,ArmouryCrateSEService,LightingService",
                string.Join(",", (object[])d["running"]), "running in list order");
            Equal(0, rig.Services.Changes().Count, "state only reads");

            var bare = new Rig();
            bare.Services.Types["LightingService"] = "Manual";
            d = (Dictionary<string, object>)bare.Send("{\"id\":2,\"cmd\":\"armoury_state\"}")["data"];
            Equal(false, d["installed"], "installed means ArmouryCrateSEService or ArmouryCrateService exists");
            bare.Services.Types["ArmouryCrateService"] = "Automatic";
            d = (Dictionary<string, object>)bare.Send("{\"id\":3,\"cmd\":\"armoury_state\"}")["data"];
            Equal(true, d["installed"], "ArmouryCrateService counts");
        }

        public static void Armoury_Stop_RecordsBeforeChanging()
        {
            var rig = ArmouryRig();
            var r = rig.Send("{\"id\":1,\"cmd\":\"armoury_stop\"}");
            True(Ok(r), "ok: " + Msg(r));
            var d = (Dictionary<string, object>)r["data"];
            var types = (Dictionary<string, object>)d["startTypes"];
            Equal(5, types.Count, "every installed listed service recorded");
            Equal("Automatic", types["ArmouryCrateControlInterface"], "type before the change");
            Equal("AutomaticDelayedStart", types["ArmouryCrateSEService"], "type before the change");
            Equal("Manual", types["LightingService"], "type before the change");
            Equal("Automatic", types["ASUSOptimization"], "stopped service recorded too");
            Equal("ArmouryCrateControlInterface,AsusAppService,ArmouryCrateSEService,LightingService",
                string.Join(",", (object[])d["running"]), "running before the change");
            // Both reads happen before the first change.
            Equal("query types", rig.Services.Calls[0], "types read first");
            Equal("query running", rig.Services.Calls[1], "running read second");
            True(rig.Services.Calls[2].StartsWith("stop "), "then changes");
        }

        // G-Helper AsusService.StopAsusServices (lines 89-94): every running service is stopped and set to
        // "Manual" when it is in servicesAC, else "Disabled" (ProcessHelper.StopDisableService: Stop-Service, then
        // Set-Service -StartupType). Services that are not running are left alone.
        public static void Armoury_Stop_SetsTypesLikeGHelper()
        {
            var rig = ArmouryRig();
            True(Ok(rig.Send("{\"id\":1,\"cmd\":\"armoury_stop\"}")), "ok");
            SeqEqual(new[] {
                "stop ArmouryCrateControlInterface Disabled",
                "stop AsusAppService Disabled",
                "stop ArmouryCrateSEService Manual",
                "stop LightingService Manual" }, rig.Services.Changes(), "changes");
            Equal("ASUSOptimization=Automatic, ArmouryCrateControlInterface=Disabled, ArmouryCrateSEService=Manual, AsusAppService=Disabled, LightingService=Manual, Spooler=Automatic+run",
                Snapshot(rig.Services), "end state");
            Equal("Manual", ArmouryServices.StopStartType("ArmouryCrateService"), "AC list -> Manual");
            Equal("Disabled", ArmouryServices.StopStartType("AsHidService"), "other list -> Disabled");
        }

        // Review focus 4: after a reboot the helper is new and the current state differs from what was recorded;
        // restore applies the recorded start types, not the current ones, and starts the recorded running services.
        public static void restore_uses_recorded_state_after_restart()
        {
            var rig = new Rig();   // fresh helper process
            var s = rig.Services;
            s.Types["ArmouryCrateControlInterface"] = "Disabled";
            s.Types["ASUSOptimization"] = "Automatic";            // recorded as Manual below
            s.Types["AsusAppService"] = "Disabled";
            s.Types["ArmouryCrateSEService"] = "Manual";
            s.Types["LightingService"] = "Manual"; s.RunningNames.Add("LightingService");   // something started it
            var r = rig.Send("{\"id\":1,\"cmd\":\"armoury_restore\",\"args\":{\"recorded\":{"
                + "\"ArmouryCrateSEService\":\"AutomaticDelayedStart\",\"ArmouryCrateControlInterface\":\"Automatic\","
                + "\"ASUSOptimization\":\"Manual\",\"AsusAppService\":\"Automatic\",\"LightingService\":\"Manual\"},"
                + "\"running\":[\"ArmouryCrateControlInterface\",\"AsusAppService\",\"ArmouryCrateSEService\",\"LightingService\"]}}");
            True(Ok(r), "restore ok: " + Msg(r));
            Equal("ASUSOptimization=Manual, ArmouryCrateControlInterface=Automatic+run, ArmouryCrateSEService=AutomaticDelayedStart+run, AsusAppService=Automatic+run, LightingService=Manual+run",
                Snapshot(s), "recorded state applied");
            SeqEqual(new[] {
                "type ArmouryCrateControlInterface Automatic",
                "type ASUSOptimization Manual",
                "type AsusAppService Automatic",
                "type ArmouryCrateSEService AutomaticDelayedStart",
                "type LightingService Manual",
                "start ArmouryCrateControlInterface Automatic",
                "start AsusAppService Automatic",
                "start ArmouryCrateSEService AutomaticDelayedStart",
                "start LightingService Manual" }, s.Changes(), "every start type first (list order), then starts (recorded order)");
        }

        // Final review I4: a running service early in the list that depends on a listed service later in the list
        // starts only after every start type is back, so the dependency is no longer Disabled.
        public static void Armoury_Restore_StartsAfterEveryStartTypeIsBack()
        {
            var rig = new Rig();
            var s = rig.Services;
            s.Types["ArmouryCrateControlInterface"] = "Disabled";
            s.Types["AsHidService"] = "Disabled";
            s.Types["LightingService"] = "Manual";
            s.DependsOn["ArmouryCrateControlInterface"] = "LightingService";   // earlier in the list than its dependency
            s.Types["LightingService"] = "Disabled";
            var r = rig.Send("{\"id\":1,\"cmd\":\"armoury_restore\",\"args\":{\"recorded\":{"
                + "\"ArmouryCrateControlInterface\":\"Automatic\",\"AsHidService\":\"Automatic\",\"LightingService\":\"Manual\"},"
                + "\"running\":[\"LightingService\",\"ArmouryCrateControlInterface\"]}}");
            True(Ok(r), "restore ok: " + Msg(r));
            SeqEqual(new[] {
                "type ArmouryCrateControlInterface Automatic",
                "type AsHidService Automatic",
                "type LightingService Manual",
                "start LightingService Manual",
                "start ArmouryCrateControlInterface Automatic" }, s.Changes(), "types, then starts in the recorded order");
            Equal("ArmouryCrateControlInterface=Automatic+run, AsHidService=Automatic, LightingService=Manual+run", Snapshot(s), "end state");

            // The fake refuses to start a service whose dependency is Disabled, like the service manager.
            var bare = new FakeServices();
            bare.Types["A"] = "Automatic"; bare.Types["B"] = "Disabled"; bare.DependsOn["A"] = "B";
            bool threw = false;
            try { bare.Start("A", "Automatic"); } catch (InvalidOperationException) { threw = true; }
            True(threw, "fake enforces the dependency");
        }

        public static void Armoury_Restore_SkipsUninstalledServices()
        {
            var rig = new Rig();
            rig.Services.Types["ArmouryCrateSEService"] = "Manual";
            var r = rig.Send("{\"id\":1,\"cmd\":\"armoury_restore\",\"args\":{\"recorded\":{\"ArmouryCrateSEService\":\"Automatic\",\"AsHidService\":\"Automatic\"},\"running\":[\"ArmouryCrateSEService\",\"AsHidService\"]}}");
            True(Ok(r), "ok: " + Msg(r));
            Equal("AsHidService", string.Join(",", (object[])((Dictionary<string, object>)r["data"])["skipped"]), "skipped");
            SeqEqual(new[] { "type ArmouryCrateSEService Automatic", "start ArmouryCrateSEService Automatic" }, rig.Services.Changes(), "only the installed one");
        }

        public static void Armoury_Restore_RefusesBadInputBeforeAnyCall()
        {
            var rig = ArmouryRig();
            string[] bad =
            {
                "{\"id\":1,\"cmd\":\"armoury_restore\",\"args\":{\"recorded\":{\"Spooler\":\"Disabled\"},\"running\":[]}}",
                "{\"id\":2,\"cmd\":\"armoury_restore\",\"args\":{\"recorded\":{\"AsHidService\":\"Boot\"},\"running\":[]}}",
                "{\"id\":3,\"cmd\":\"armoury_restore\",\"args\":{\"recorded\":{\"AsHidService\":\"Manual\"},\"running\":[\"LightingService\"]}}",
                "{\"id\":4,\"cmd\":\"armoury_restore\",\"args\":{\"recorded\":{\"AsHidService\":7},\"running\":[]}}",
                "{\"id\":5,\"cmd\":\"armoury_restore\",\"args\":{\"recorded\":{},\"running\":[\"x\\\" & sc delete\"]}}",
            };
            foreach (string b in bad)
            {
                var r = rig.Send(b);
                True(!Ok(r) && Msg(r).StartsWith("Refused"), "refused: " + b + " -> " + Msg(r));
            }
            Equal(0, rig.Services.Calls.Count, "no service call at all");
        }

        public static void Armoury_PartialFailure_ReportsServiceName_AndRollsBack()
        {
            var rig = ArmouryRig();
            string before = Snapshot(rig.Services);
            rig.Services.FailStop.Add("ArmouryCrateSEService");   // third stop: stops it, then fails to set the type
            var r = rig.Send("{\"id\":1,\"cmd\":\"armoury_stop\"}");
            True(!Ok(r), "failure reported");
            True(Msg(r).Contains("ArmouryCrateSEService") && Msg(r).Contains("access denied"), "names the service and the reason: " + Msg(r));
            Equal("ArmouryCrateSEService", ((Dictionary<string, object>)r["data"])["failed"], "data.failed");
            Equal(true, ((Dictionary<string, object>)r["data"])["rolledBack"], "data.rolledBack");
            Equal(before, Snapshot(rig.Services), "every service back as it was");
            SeqEqual(new[] {
                "stop ArmouryCrateControlInterface Disabled",
                "stop AsusAppService Disabled",
                "stop ArmouryCrateSEService Manual",
                "start ArmouryCrateSEService AutomaticDelayedStart",
                "start AsusAppService Automatic",
                "start ArmouryCrateControlInterface Automatic" }, rig.Services.Changes(), "rolled back in reverse");

            // Restore failing half-way rolls back to the state before the restore (the switch stays on).
            rig = new Rig();
            var s = rig.Services;
            s.Types["ArmouryCrateControlInterface"] = "Disabled";
            s.Types["ASUSOptimization"] = "Automatic";
            s.Types["ArmouryCrateSEService"] = "Manual";
            before = Snapshot(s);
            s.FailStart.Add("ArmouryCrateSEService");
            r = rig.Send("{\"id\":2,\"cmd\":\"armoury_restore\",\"args\":{\"recorded\":{\"ArmouryCrateControlInterface\":\"Automatic\",\"ASUSOptimization\":\"Manual\",\"ArmouryCrateSEService\":\"Automatic\"},\"running\":[\"ArmouryCrateControlInterface\",\"ArmouryCrateSEService\"]}}");
            True(!Ok(r) && Msg(r).Contains("ArmouryCrateSEService"), "restore failure names the service: " + Msg(r));
            Equal(before, Snapshot(s), "restore rolled back");

            // A rollback that fails too is reported with its service name.
            rig = ArmouryRig();
            rig.Services.FailStop.Add("ArmouryCrateSEService");
            rig.Services.FailStart.Add("AsusAppService");
            r = rig.Send("{\"id\":3,\"cmd\":\"armoury_stop\"}");
            True(!Ok(r) && Msg(r).Contains("Rollback also failed for AsusAppService"), "rollback failure listed: " + Msg(r));
            Equal(false, ((Dictionary<string, object>)r["data"])["rolledBack"], "data.rolledBack false");
            True(rig.Services.RunningNames.Contains("ArmouryCrateControlInterface"), "rollback continues past a failure");
        }
    }
}
