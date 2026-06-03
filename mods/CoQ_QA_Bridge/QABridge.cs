using System;
using System.Collections.Concurrent;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using HarmonyLib;
using XRL;
using XRL.Core;
using XRL.World;
using XRL.World.Parts;

// =====================================================================
// Bridge-Maker QA Bridge — Caves of Qud Harmony mod.
//
// A background TCP listener speaks the length-prefixed JSON protocol used by
// SocketTransport / mock_coq_server. Requests are queued and drained on the main
// thread by a Harmony postfix on XRLCore.PlayerTurn, where it is safe to read and
// mutate game state. API verified by reflection against Assembly-CSharp.dll.
//
// QA value lives in the ORACLES, not the walking:
//   * EXCEPTION  — a Harmony finalizer captures any exception thrown during the
//                  player turn (the #1 automated-playtest signal: real crashes).
//   * INVARIANT  — HP<0, missing cell, out-of-zone position are flagged.
//   * SOFTLOCK   — no positional change for many turns.
//
// Protocol (identical to the mock):
//   in : {"cmd":"reset"} | {"cmd":"step","action":<int>} | {"cmd":"bye"}
//   out: {"obs":{...}, "reward_hint":0.0, "terminated":bool, "truncated":false,
//         "anomaly":str|null, "info":{}}
// =====================================================================

namespace BridgeMaker
{
    public static class QABridgeServer
    {
        const int PORT = 50545;
        const int ZONE_W = 80, ZONE_H = 25;

        // 8-directional movement + wait, matching DotNetConnector.ACTION_BINDINGS.
        static readonly string[] DIRS = { "N", "S", "E", "W", "NE", "NW", "SE", "SW" };

        class Pending
        {
            public string Cmd;
            public int Action;
            public string Response;
            public readonly ManualResetEventSlim Done = new ManualResetEventSlim(false);
        }

        static readonly ConcurrentQueue<Pending> Inbox = new ConcurrentQueue<Pending>();
        static TcpListener Listener;
        static volatile bool Running;

        static int LastX = int.MinValue, LastY = int.MinValue, StillTurns, StepCount;
        static volatile string PendingException;  // set by the crash finalizer

        public static void EnsureStarted()
        {
            if (Running) return;
            Running = true;
            Listener = new TcpListener(IPAddress.Loopback, PORT);
            Listener.Start();
            new Thread(AcceptLoop) { IsBackground = true, Name = "QABridgeAccept" }.Start();
            UnityEngine.Debug.Log($"[QABridge] Listening on 127.0.0.1:{PORT}");
        }

        public static void RecordException(Exception e)
        {
            PendingException = "EXCEPTION:" + e.GetType().Name;
            UnityEngine.Debug.LogWarning("[QABridge] captured turn exception: " + e);
        }

        static void AcceptLoop()
        {
            while (Running)
            {
                try
                {
                    var client = Listener.AcceptTcpClient();
                    client.NoDelay = true;
                    new Thread(() => ClientLoop(client)) { IsBackground = true }.Start();
                }
                catch (SocketException) { return; }
                catch (Exception e) { UnityEngine.Debug.LogWarning($"[QABridge] accept: {e.Message}"); }
            }
        }

        static void ClientLoop(TcpClient client)
        {
            using (client)
            using (var ns = client.GetStream())
            {
                while (Running)
                {
                    var body = ReadFrame(ns);
                    if (body == null) return;
                    string cmd = ExtractString(body, "cmd");
                    if (cmd == "bye") return;

                    var pending = new Pending { Cmd = cmd, Action = ExtractInt(body, "action", 8) };
                    Inbox.Enqueue(pending);
                    pending.Done.Wait(15000);
                    WriteFrame(ns, Encoding.UTF8.GetBytes(pending.Response ?? "{}"));
                }
            }
        }

        // Drained from the player-turn Harmony postfix (main thread).
        public static void Pump()
        {
            while (Inbox.TryDequeue(out var p))
            {
                try
                {
                    if (p.Cmd == "step") ApplyAction(p.Action);
                    StepCount++;
                    p.Response = BuildStateJson();
                }
                catch (Exception e)
                {
                    RecordException(e);
                    p.Response = "{\"obs\":{},\"reward_hint\":0.0,\"terminated\":true,"
                               + "\"truncated\":false,\"anomaly\":\"EXCEPTION:" + e.GetType().Name + "\",\"info\":{}}";
                }
                finally { p.Done.Set(); }
            }
        }

        static void ApplyAction(int action)
        {
            var player = The.Player;
            if (player == null) return;
            if (action >= 0 && action < DIRS.Length)
                player.Move(DIRS[action]);   // optional params default; bumps = attack/dig
            // action == DIRS.Length -> WAIT (let the turn pass)
        }

        static string BuildStateJson()
        {
            var player = The.Player;
            var cell = The.PlayerCell;

            float hp = 0f, hpMax = 0f, level = 1f, hunger = 0f;
            int x = cell?.X ?? -1, y = cell?.Y ?? -1, threats = 0;

            var hpStat = player?.GetStat("Hitpoints");
            if (hpStat != null) { hp = hpStat.Value; hpMax = hpStat.BaseValue; }
            var lvlStat = player?.GetStat("Level");
            if (lvlStat != null) level = lvlStat.Value;
            var stomach = player?.GetPart<Stomach>();
            if (stomach != null) hunger = stomach.HungerLevel;
            if (cell?.ParentZone != null)
            {
                foreach (var go in cell.ParentZone.GetObjectsWithPart("Brain"))
                    if (go.IsHostileTowards(player)) threats++;
                if (threats > 10) threats = 10;
            }

            string anomaly = DetectAnomaly(x, y, hp, cell);
            bool terminated = hp <= 0f || (anomaly != null && anomaly.StartsWith("EXCEPTION"));

            var sb = new StringBuilder(256);
            sb.Append("{\"obs\":{");
            sb.AppendFormat(CultureInfo.InvariantCulture,
                "\"coq_hp\":{0},\"coq_hp_max\":{1},\"coq_x\":{2},\"coq_y\":{3},\"coq_depth\":{4}," +
                "\"coq_hunger\":{5},\"coq_level\":{6},\"coq_turn\":{7},\"coq_threats\":{8}",
                hp, hpMax, Math.Max(x, 0), Math.Max(y, 0), 0f, hunger, level, StepCount, threats);
            sb.Append("},\"reward_hint\":0.0,");
            sb.AppendFormat("\"terminated\":{0},\"truncated\":false,", terminated ? "true" : "false");
            sb.Append(anomaly == null ? "\"anomaly\":null," : "\"anomaly\":\"" + anomaly + "\",");
            sb.Append("\"info\":{}}");
            return sb.ToString();
        }

        // --- Oracles ---------------------------------------------------------
        static string DetectAnomaly(int x, int y, float hp, Cell cell)
        {
            // 1) Crash captured by the finalizer takes priority.
            if (PendingException != null)
            {
                var e = PendingException;
                PendingException = null;
                return e;
            }
            // 2) Invariants that should never hold in a correct game.
            if (cell == null) return "INVARIANT_NO_CELL";
            if (hp < 0f) return "INVARIANT_HP_NEGATIVE";
            if (x < 0 || x >= ZONE_W || y < 0 || y >= ZONE_H) return "INVARIANT_POS_OOB";
            // 3) Softlock: no positional change across many turns.
            if (x == LastX && y == LastY) StillTurns++;
            else { StillTurns = 0; LastX = x; LastY = y; }
            if (StillTurns >= 25) return "SOFTLOCK_SUSPECTED";
            return null;
        }

        // --- length-prefixed (4-byte BE) framing -----------------------------
        static byte[] ReadFrame(NetworkStream ns)
        {
            var header = ReadExact(ns, 4);
            if (header == null) return null;
            int len = (header[0] << 24) | (header[1] << 16) | (header[2] << 8) | header[3];
            return ReadExact(ns, len);
        }

        static byte[] ReadExact(NetworkStream ns, int n)
        {
            var buf = new byte[n];
            int got = 0;
            while (got < n)
            {
                int r;
                try { r = ns.Read(buf, got, n - got); }
                catch { return null; }
                if (r <= 0) return null;
                got += r;
            }
            return buf;
        }

        static void WriteFrame(NetworkStream ns, byte[] body)
        {
            var header = new byte[4];
            header[0] = (byte)(body.Length >> 24);
            header[1] = (byte)(body.Length >> 16);
            header[2] = (byte)(body.Length >> 8);
            header[3] = (byte)body.Length;
            ns.Write(header, 0, 4);
            ns.Write(body, 0, body.Length);
            ns.Flush();
        }

        // Tiny field extractors (no JSON dep inside the mod).
        static string ExtractString(byte[] body, string key)
        {
            string s = Encoding.UTF8.GetString(body);
            int i = s.IndexOf("\"" + key + "\"", StringComparison.Ordinal);
            if (i < 0) return null;
            int q1 = s.IndexOf('"', s.IndexOf(':', i) + 1);
            int q2 = q1 >= 0 ? s.IndexOf('"', q1 + 1) : -1;
            return (q1 >= 0 && q2 > q1) ? s.Substring(q1 + 1, q2 - q1 - 1) : null;
        }

        static int ExtractInt(byte[] body, string key, int fallback)
        {
            string s = Encoding.UTF8.GetString(body);
            int i = s.IndexOf("\"" + key + "\"", StringComparison.Ordinal);
            if (i < 0) return fallback;
            int c = s.IndexOf(':', i) + 1;
            var num = new StringBuilder();
            while (c < s.Length && (char.IsDigit(s[c]) || s[c] == '-')) num.Append(s[c++]);
            return int.TryParse(num.ToString(), out int v) ? v : fallback;
        }
    }

    [HarmonyPatch(typeof(XRLCore), "PlayerTurn")]
    public static class QABridge_PlayerTurn
    {
        static void Postfix()
        {
            QABridgeServer.EnsureStarted();
            QABridgeServer.Pump();
        }

        // Crash oracle: capture any exception thrown during the turn, then let it
        // propagate so the game still behaves exactly as it would unmodified.
        static Exception Finalizer(Exception __exception)
        {
            if (__exception != null) QABridgeServer.RecordException(__exception);
            return __exception;
        }
    }
}
