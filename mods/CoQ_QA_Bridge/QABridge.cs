using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
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
// A background TCP listener accepts the length-prefixed JSON protocol used by
// SocketTransport / mock_coq_server. Requests are queued and drained on the main
// thread by a Harmony postfix on the player turn, where it is safe to read/mutate
// game state. State is read by FIELD NAME from XRL.The.Player (version-resilient).
//
// Protocol (identical to the mock):
//   in : {"cmd":"reset"} | {"cmd":"step","action":<int>} | {"cmd":"bye"}
//   out: {"obs":{...}, "reward_hint":0.0, "terminated":bool, "truncated":false,
//         "anomaly":str|null, "info":{}}
//
// NOTE: action verbs use GameObject.Move(direction). If a future CoQ build renames
// movement, adjust ApplyAction() — the state-read path is independent of it.
// =====================================================================

namespace BridgeMaker
{
    public static class QABridgeServer
    {
        const int PORT = 50545;

        // One pending request at a time keeps the RL<->turn handshake in lockstep.
        class Pending
        {
            public string Cmd;
            public int Action;
            public string Response;
            public readonly ManualResetEventSlim Done = new ManualResetEventSlim(false);
        }

        static readonly ConcurrentQueue<Pending> Inbox = new ConcurrentQueue<Pending>();
        static TcpListener Listener;
        static Thread AcceptThread;
        static volatile bool Running;

        // Stuck-detection for SOFTLOCK heuristic.
        static int LastX = int.MinValue, LastY = int.MinValue, StillTurns;

        public static void EnsureStarted()
        {
            if (Running) return;
            Running = true;
            Listener = new TcpListener(IPAddress.Loopback, PORT);
            Listener.Start();
            AcceptThread = new Thread(AcceptLoop) { IsBackground = true, Name = "QABridgeAccept" };
            AcceptThread.Start();
            UnityEngine.Debug.Log($"[QABridge] Listening on 127.0.0.1:{PORT}");
        }

        static void AcceptLoop()
        {
            while (Running)
            {
                try
                {
                    var client = Listener.AcceptTcpClient();
                    client.NoDelay = true;
                    var t = new Thread(() => ClientLoop(client)) { IsBackground = true };
                    t.Start();
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

                    var pending = new Pending { Cmd = cmd, Action = ExtractInt(body, "action", 4) };
                    Inbox.Enqueue(pending);
                    // Block until the main-thread hook fills the response.
                    pending.Done.Wait(15000);
                    var outBytes = Encoding.UTF8.GetBytes(pending.Response ?? "{}");
                    WriteFrame(ns, outBytes);
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
                    p.Response = BuildStateJson();
                }
                catch (Exception e)
                {
                    p.Response = "{\"obs\":{},\"terminated\":true,\"truncated\":false,\"anomaly\":\"BRIDGE_ERROR\",\"info\":{}}";
                    UnityEngine.Debug.LogWarning($"[QABridge] pump: {e.Message}");
                }
                finally { p.Done.Set(); }
            }
        }

        static void ApplyAction(int action)
        {
            var player = The.Player;
            if (player == null) return;
            switch (action)
            {
                case 0: player.Move("N"); break;
                case 1: player.Move("S"); break;
                case 2: player.Move("E"); break;
                case 3: player.Move("W"); break;
                case 4: break;                       // WAIT
                case 5: player.Move("N", Forced: false); break; // INTERACT ~ bump
            }
        }

        static string BuildStateJson()
        {
            var player = The.Player;
            var cell = player?.CurrentCell;
            float hp = ReadStat(player, "Hitpoints", out float hpMax);
            int x = cell?.X ?? 0, y = cell?.Y ?? 0;
            float hunger = ReadHunger(player);
            float level = ReadStat(player, "Level", out _);
            float turn = SafeTurns();
            int threats = CountHostiles(cell);
            string anomaly = DetectAnomaly(x, y, hp);
            bool terminated = hp <= 0f;

            var sb = new StringBuilder(256);
            sb.Append("{\"obs\":{");
            sb.AppendFormat(System.Globalization.CultureInfo.InvariantCulture,
                "\"coq_hp\":{0},\"coq_hp_max\":{1},\"coq_x\":{2},\"coq_y\":{3},\"coq_depth\":{4}," +
                "\"coq_hunger\":{5},\"coq_level\":{6},\"coq_turn\":{7},\"coq_threats\":{8}",
                hp, hpMax, x, y, 0f, hunger, level, turn, threats);
            sb.Append("},\"reward_hint\":0.0,");
            sb.AppendFormat("\"terminated\":{0},\"truncated\":false,",
                terminated ? "true" : "false");
            sb.Append(anomaly == null ? "\"anomaly\":null," : $"\"anomaly\":\"{anomaly}\",");
            sb.Append("\"info\":{}}");
            return sb.ToString();
        }

        static string DetectAnomaly(int x, int y, float hp)
        {
            if (x == LastX && y == LastY) StillTurns++;
            else { StillTurns = 0; LastX = x; LastY = y; }
            if (StillTurns >= 12) return "SOFTLOCK_SUSPECTED"; // no positional change for many turns
            return null;
        }

        static float ReadStat(GameObject who, string stat, out float max)
        {
            max = 0f;
            try
            {
                var s = who?.GetStat(stat);
                if (s == null) return 0f;
                max = s.BaseValue;
                return s.Value;
            }
            catch { return 0f; }
        }

        static float ReadHunger(GameObject who)
        {
            try
            {
                var stomach = who?.GetPart<Stomach>();
                return stomach != null ? (float)stomach.HungerLevel : 0f;
            }
            catch { return 0f; }
        }

        static float SafeTurns()
        {
            try { return The.Game != null ? (float)The.Game.Turns : 0f; }
            catch { return 0f; }
        }

        static int CountHostiles(Cell cell)
        {
            try
            {
                if (cell?.ParentZone == null) return 0;
                int n = 0;
                foreach (var go in cell.ParentZone.GetObjectsWithPart("Brain"))
                    if (go.IsHostileTowards(The.Player)) n++;
                return Math.Min(n, 10);
            }
            catch { return 0; }
        }

        // --- length-prefixed (4-byte BE) framing ---
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

        // Tiny field extractors (avoid pulling a JSON dep into the mod).
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
    }
}
