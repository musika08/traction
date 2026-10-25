using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using Ally.Shared;
using Microsoft.Win32.SafeHandles;

namespace Traction.Helper
{
    // Input reports from the controller's 0x5A collection. Read blocks until a report arrives and throws IOException
    // when the device is gone or the source was closed.
    public interface IReportSource
    {
        bool Open();
        byte[] Read();
        void Close();
    }

    // The collection AsusHid.Select returns, opened read only and shared (GENERIC_READ, FILE_SHARE_READ |
    // FILE_SHARE_WRITE), so Armoury Crate and the feature writes keep working. Nothing is ever written to it.
    public sealed class HidReportSource : IReportSource
    {
        private const uint GENERIC_READ = 0x80000000;
        private const uint FILE_SHARE_READ = 0x01;
        private const uint FILE_SHARE_WRITE = 0x02;
        private const uint OPEN_EXISTING = 3;
        private const int HIDP_STATUS_SUCCESS = 0x00110000;

        [StructLayout(LayoutKind.Sequential)]
        private struct HIDP_CAPS
        {
            public ushort Usage;
            public ushort UsagePage;
            public ushort InputReportByteLength;
            public ushort OutputReportByteLength;
            public ushort FeatureReportByteLength;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 17)]
            public ushort[] Reserved;
            public ushort NumberLinkCollectionNodes;
            public ushort NumberInputButtonCaps;
            public ushort NumberInputValueCaps;
            public ushort NumberInputDataIndices;
            public ushort NumberOutputButtonCaps;
            public ushort NumberOutputValueCaps;
            public ushort NumberOutputDataIndices;
            public ushort NumberFeatureButtonCaps;
            public ushort NumberFeatureValueCaps;
            public ushort NumberFeatureDataIndices;
        }

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern SafeFileHandle CreateFile(string name, uint access, uint share, IntPtr sa, uint disposition,
            uint flags, IntPtr template);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool ReadFile(SafeFileHandle h, byte[] buffer, int toRead, out int read, IntPtr overlapped);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CancelIoEx(SafeFileHandle h, IntPtr overlapped);

        [DllImport("hid.dll")]
        private static extern bool HidD_GetPreparsedData(SafeFileHandle h, out IntPtr preparsed);

        [DllImport("hid.dll")]
        private static extern bool HidD_FreePreparsedData(IntPtr preparsed);

        [DllImport("hid.dll")]
        private static extern int HidP_GetCaps(IntPtr preparsed, out HIDP_CAPS caps);

        private readonly object gate = new object();
        private SafeFileHandle handle;
        private int length;

        public bool Open()
        {
            Close();
            HidCollection c = AsusHid.Select(new Win32HidBus().List());
            if (c == null || string.IsNullOrEmpty(c.Path)) return false;
            SafeFileHandle h = CreateFile(c.Path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, IntPtr.Zero,
                OPEN_EXISTING, 0, IntPtr.Zero);
            if (h.IsInvalid) { h.Dispose(); return false; }
            int len = 0;
            IntPtr pp;
            if (HidD_GetPreparsedData(h, out pp))
            {
                HIDP_CAPS caps;
                if (HidP_GetCaps(pp, out caps) == HIDP_STATUS_SUCCESS) len = caps.InputReportByteLength;
                HidD_FreePreparsedData(pp);
            }
            if (len <= 0) { h.Dispose(); return false; }
            lock (gate)
            {
                handle = h;
                length = len;
            }
            return true;
        }

        public byte[] Read()
        {
            SafeFileHandle h;
            int len;
            lock (gate)
            {
                h = handle;
                len = length;
            }
            if (h == null || h.IsClosed) throw new IOException("The controller collection is not open.");
            var buf = new byte[len];
            int n;
            bool ok;
            try { ok = ReadFile(h, buf, buf.Length, out n, IntPtr.Zero); }
            catch (ObjectDisposedException) { throw new IOException("The controller collection was closed."); }
            if (!ok) throw new IOException("Reading the controller failed (error " + Marshal.GetLastWin32Error() + ").");
            if (n < buf.Length) Array.Resize(ref buf, n);
            return buf;
        }

        // Cancels a pending Read (it then throws IOException) and closes the handle.
        public void Close()
        {
            SafeFileHandle h;
            lock (gate)
            {
                h = handle;
                handle = null;
            }
            if (h == null) return;
            try { if (!h.IsClosed) CancelIoEx(h, IntPtr.Zero); }
            catch (ObjectDisposedException) { }
            h.Dispose();
        }
    }

    // Runs the chosen action when the Armoury Crate button sends input report 5A EC. A reader thread runs while the
    // action is not "nothing": open (on failure wait RetryMs and try again), read, Handle, repeat; a failed read
    // (sleep, unplug) closes, waits RetryMs and reopens. Setting "nothing" closes the collection and ends the thread.
    public sealed class ButtonListener
    {
        public const byte TriggerId = 0x5A;
        public const byte TriggerCode = 0xEC;
        public const double BounceSeconds = 0.5;
        public const int RetryMs = 2000;
        public const int StopWaitMs = 1000;

        private readonly IReportSource source;
        private readonly IInputSender sender;
        private readonly Func<DateTime> clock;
        private readonly Action<int> wait;
        private readonly object gate = new object();
        private readonly object fireGate = new object();

        private volatile string action = "nothing";
        private int generation;            // bumped on every start and stop; a reader whose generation is old exits
        private Thread thread;              // the newest reader (it may still be ending after a stop)
        private int threadGen;             // the generation that reader runs for
        private ManualResetEvent stopEvent;
        private DateTime? lastFired;
        private int opens;

        // wait null: the reader sleeps on an event that a stop sets, so "nothing" ends it at once even mid-retry.
        public ButtonListener(IReportSource source, IInputSender sender, Func<DateTime> clock, Action<int> wait)
        {
            if (source == null) throw new ArgumentNullException("source");
            if (sender == null) throw new ArgumentNullException("sender");
            this.source = source;
            this.sender = sender;
            this.clock = clock ?? (() => DateTime.UtcNow);
            this.wait = wait;
        }

        public string Action { get { return action; } }

        public bool Running
        {
            get { lock (gate) return thread != null && thread.IsAlive; }
        }

        // Successful opens of the collection.
        public int Opens { get { return Interlocked.CompareExchange(ref opens, 0, 0); } }

        public void SetAction(string id)
        {
            if (ButtonActions.Steps(id) == null) throw new ArgumentException("Unknown button action '" + id + "'.");
            Thread stopping = null;
            lock (gate)
            {
                if (id == action) return;
                action = id;
                if (id == "nothing")
                {
                    generation++;
                    if (stopEvent != null) stopEvent.Set();
                    source.Close();
                    stopping = thread;
                }
                else if (thread == null || !thread.IsAlive || threadGen != generation)
                {
                    // No reader for the current generation (none yet, or the last one was stopped and may still be
                    // ending; it exits on its own without touching the source).
                    generation++;
                    int gen = generation;
                    threadGen = gen;
                    var ev = new ManualResetEvent(false);
                    stopEvent = ev;
                    thread = new Thread(() => Loop(gen, ev)) { IsBackground = true, Name = "Armoury Crate button" };
                    thread.Start();
                }
                // Another action while the reader runs: it picks the new action up on the next press.
            }
            if (stopping != null) stopping.Join(StopWaitMs);
        }

        // True when the report is 5A EC, an action is set and the last press that fired is at least BounceSeconds
        // ago; the action is then sent. The action is read once, so a change mid-press runs the old or the new one.
        public bool Handle(byte[] report)
        {
            if (report == null || report.Length < 2 || report[0] != TriggerId || report[1] != TriggerCode) return false;
            IList<InputStep> steps = ButtonActions.Steps(action);
            if (steps == null || steps.Count == 0) return false;
            DateTime now = clock();
            lock (fireGate)
            {
                if (lastFired.HasValue)
                {
                    double since = (now - lastFired.Value).TotalSeconds;
                    if (since >= 0 && since < BounceSeconds) return false;
                }
                lastFired = now;
            }
            try { sender.Send(steps); }
            catch (Exception ex) { Log("sending the button action failed: " + ex.Message); }
            return true;
        }

        private bool Current(int gen)
        {
            lock (gate) return gen == generation && action != "nothing";
        }

        private void Pause(ManualResetEvent ev)
        {
            if (wait != null) wait(RetryMs);
            else ev.WaitOne(RetryMs);
        }

        private void Loop(int gen, ManualResetEvent ev)
        {
            bool open = false;
            while (true)
            {
                try
                {
                    if (!open)
                    {
                        // Opened under the lock, so a stop cannot slip in between the check and the open.
                        bool ok;
                        lock (gate)
                        {
                            if (gen != generation || action == "nothing") return;
                            try { ok = source.Open(); }
                            catch (Exception ex) { Log("opening the controller failed: " + ex.Message); ok = false; }
                            if (ok) Interlocked.Increment(ref opens);
                        }
                        if (!ok)
                        {
                            Pause(ev);
                            continue;
                        }
                        open = true;
                    }

                    byte[] report;
                    try { report = source.Read(); }
                    catch (Exception ex)
                    {
                        open = false;
                        lock (gate)
                        {
                            if (gen != generation || action == "nothing") return;   // stopped: the source is not ours
                            source.Close();
                        }
                        Log("reading the controller failed, reopening in " + RetryMs + " ms: " + ex.Message);
                        Pause(ev);
                        continue;
                    }
                    if (!Current(gen)) return;
                    Handle(report);
                }
                catch (Exception ex)
                {
                    // Never ends the reader; only a stop does.
                    Log("button reader: " + ex.Message);
                    if (!Current(gen)) return;
                    Pause(ev);
                }
            }
        }

        private static void Log(string message)
        {
            try { Console.Error.WriteLine("traction-helper: " + message); }
            catch (Exception) { }
        }
    }
}
