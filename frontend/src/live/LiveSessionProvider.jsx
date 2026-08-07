import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { openLiveSocket } from "../api/client";
import {
  TrackRecorder,
  captureMicrophone,
  captureTabAudio,
  grabFrame,
  isCaptureSupported,
} from "../lib/audioCapture";

/**
 * The live meeting session, owned above the router.
 *
 * This used to live inside `LivePanel`, which meant the websocket and the
 * recorders were tied to that component's lifetime. Switching to "Past
 * meetings" mid-meeting unmounted the panel, and its cleanup closed the
 * socket and stopped the microphone — **the recording silently ended**.
 * Nothing said so; you came back to a dead session.
 *
 * A meeting is not a property of a screen. It belongs to the app, so it
 * lives here, and the floating bar can follow you onto any tab with the
 * pause and end controls still wired to a session that is genuinely
 * still running.
 *
 * Everything else is unchanged and deliberate:
 *
 * - Device permission is requested *before* the socket opens, so a
 *   refused microphone never leaves a half-started session on the server.
 * - Pause stops the recorders first, then tells the server, so a chunk
 *   already in flight arrives before the server flips state and is
 *   dropped there.
 * - The server is authoritative about paused state.
 */
const LiveSessionContext = createContext(null);

const IDLE = {
  phase: "idle",
  meetingId: null,
  segments: [],
  candidates: [],
  warnings: [],
  tracks: { mic: false, remote: false },
  paused: false,
};

export function LiveSessionProvider({ children }) {
  const [phase, setPhase] = useState("idle"); // idle | live | finalizing | ended
  const [meetingId, setMeetingId] = useState(null);
  const [roster, setRoster] = useState([]);
  const [segments, setSegments] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [engines, setEngines] = useState({});
  const [tracks, setTracks] = useState(IDLE.tracks);
  const [paused, setPaused] = useState(false);
  // Hiding Naina is a user preference about the session, not about
  // whichever screen happens to be open.
  const [barHidden, setBarHidden] = useState(false);
  // Names read off the shared screen, awaiting a human's yes or no.
  // They are NOT participants and cannot own anything until confirmed.
  const [proposedNames, setProposedNames] = useState([]);
  const [scanning, setScanning] = useState(false);
  const [canReadScreen, setCanReadScreen] = useState(false);

  const socketRef = useRef(null);
  const recordersRef = useRef([]);
  // Held only when the user opted into reading names off the screen.
  const screenRef = useRef(null);
  const onEndedRef = useRef(null);

  const active = phase === "live" || phase === "finalizing";

  const stopRecorders = useCallback(() => {
    recordersRef.current.forEach((recorder) => {
      try {
        recorder.stop();
      } catch {
        /* already stopped */
      }
    });
    recordersRef.current = [];
    screenRef.current?.getTracks().forEach((track) => track.stop());
    screenRef.current = null;
    setTracks(IDLE.tracks);
  }, []);

  const send = useCallback((payload) => {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
  }, []);

  /**
   * Only tear down when the whole app goes away.
   *
   * The empty dependency list is the point: this provider sits above the
   * view switch, so this cleanup runs on a real page unload rather than
   * on every navigation.
   */
  useEffect(() => {
    return () => {
      recordersRef.current.forEach((r) => {
        try {
          r.stop();
        } catch {
          /* already stopped */
        }
      });
      socketRef.current?.close();
    };
  }, []);

  /**
   * Closing the tab mid-meeting loses audio that cannot be recovered, so
   * the browser gets to ask first. Only while actually recording — a
   * confirm dialog on every navigation would be its own kind of rude.
   */
  useEffect(() => {
    if (!active) return undefined;
    const warn = (event) => {
      event.preventDefault();
      event.returnValue = "";
      return "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [active]);

  const applySnapshot = useCallback((message) => {
    if (message.segments) setSegments(message.segments);
    if (message.candidates) setCandidates(message.candidates);
    if (message.warnings) setWarnings(message.warnings);
  }, []);

  const start = useCallback(
    async ({ title, participants, selfName, captureTab, readScreen = false, onEnded }) => {
      setError(null);
      onEndedRef.current = onEnded || null;

      if (!isCaptureSupported()) {
        setError("This browser cannot capture audio. Use Chrome or Edge.");
        return false;
      }

      let micStream = null;
      let tabStream = null;
      let screenStream = null;
      try {
        micStream = await captureMicrophone();
        if (captureTab) {
          const captured = await captureTabAudio({ keepVideo: readScreen });
          tabStream = captured.audio;
          screenStream = captured.video;
        }
      } catch (err) {
        micStream?.getTracks().forEach((track) => track.stop());
        setError(err.message);
        return false;
      }
      screenRef.current = screenStream;
      setCanReadScreen(Boolean(screenStream));
      setProposedNames([]);

      setSegments([]);
      setCandidates([]);
      setWarnings([]);
      setStatus(null);
      setPaused(false);
      setBarHidden(false);

      const socket = openLiveSocket();
      socketRef.current = socket;

      socket.onopen = () =>
        socket.send(
          JSON.stringify({
            type: "start",
            title,
            meeting_date: new Date().toISOString().slice(0, 10),
            participants,
            self_participant: selfName,
            consent_acknowledged: true,
            consent_note: "Reviewer confirmed in-app that participants were informed.",
          })
        );

      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        switch (message.type) {
          case "started": {
            setMeetingId(message.meeting_id);
            setRoster(message.participants || []);
            setEngines({ transcriber: message.transcriber, extractor: message.extractor });
            setPhase("live");
            if (!message.audio_enabled) {
              setWarnings((current) => [
                ...current,
                "No speech-to-text engine is configured — set GROQ_API_KEY or SARVAM_API_KEY. " +
                  "You can still type lines below.",
              ]);
            }

            const chunkSeconds = message.chunk_seconds || 6;
            const started = [];
            const forward = (chunk) => socket.send(JSON.stringify({ type: "audio", ...chunk }));
            if (micStream) {
              const recorder = new TrackRecorder(micStream, "mic", forward, chunkSeconds);
              recorder.start();
              started.push(recorder);
              setTracks((t) => ({ ...t, mic: true }));
            }
            if (tabStream) {
              const recorder = new TrackRecorder(tabStream, "remote", forward, chunkSeconds);
              recorder.start();
              started.push(recorder);
              setTracks((t) => ({ ...t, remote: true }));
            }
            recordersRef.current = started;
            break;
          }
          case "segments":
            setSegments((current) => [...current, ...message.segments]);
            break;
          case "snapshot":
          case "tagged":
            applySnapshot(message);
            break;
          case "warnings":
            setWarnings(message.warnings || []);
            break;
          case "participants":
            setRoster(message.participants || []);
            // Anything just accepted is no longer a proposal.
            setProposedNames((current) =>
              current.filter(
                (proposal) =>
                  !(message.added || []).some(
                    (added) => added.name.toLowerCase() === proposal.name.toLowerCase()
                  )
              )
            );
            break;
          case "recording":
            setPaused(Boolean(message.paused));
            if (message.segments) setSegments((current) => [...current, ...message.segments]);
            break;
          case "finalizing":
            setPhase("finalizing");
            setStatus(message.step);
            break;
          case "ended":
            stopRecorders();
            applySnapshot(message);
            setPhase("ended");
            setStatus(message.executive_summary || null);
            onEndedRef.current?.(message.meeting_id || meetingId);
            break;
          case "error":
            setError(message.error);
            if (message.code === "consent_required" || message.code === "participants_required") {
              stopRecorders();
              setPhase("idle");
            }
            break;
          default:
            break;
        }
      };

      socket.onerror = () => setError("Websocket failed. Is the backend running on :8000?");
      socket.onclose = () => stopRecorders();
      return true;
    },
    [applySnapshot, stopRecorders, meetingId]
  );

  /**
   * Read participant names off the shared screen.
   *
   * On demand rather than on a timer: the point is to learn who is in
   * the room, not to watch the screen. OCR runs entirely in this
   * browser -- no frame is uploaded anywhere -- and everything it finds
   * is a *proposal*. A name on a video tile is a guess in a confident
   * font, and a wrong one would become an owner the gate approves.
   */
  const scanScreenForNames = useCallback(async () => {
    if (!screenRef.current) {
      setError(
        "Naina cannot see the meeting. Start the meeting with " +
          "\"Let Naina read participant names\" ticked to enable this."
      );
      return [];
    }

    setScanning(true);
    try {
      const { detectNames } = await import("../lib/nameDetection");
      const canvas = await grabFrame(screenRef.current);
      const known = roster.map((p) => p.name);
      const found = await detectNames(canvas, { known });

      setProposedNames((current) => {
        const seen = new Set(current.map((c) => c.name.toLowerCase()));
        return [...current, ...found.filter((f) => !seen.has(f.name.toLowerCase()))];
      });
      return found;
    } catch (err) {
      setError(`Could not read the screen: ${err.message}`);
      return [];
    } finally {
      setScanning(false);
    }
  }, [roster]);

  const confirmNames = useCallback(
    (names, reviewer = "reviewer") => {
      if (!names.length) return;
      send({ type: "add_participants", names, source: "screen_ocr", reviewer });
    },
    [send]
  );

  const dismissName = useCallback((name) => {
    setProposedNames((current) =>
      current.filter((c) => c.name.toLowerCase() !== name.toLowerCase())
    );
  }, []);

  const pause = useCallback(() => {
    recordersRef.current.forEach((recorder) => recorder.pause());
    setPaused(true);
    send({ type: "pause" });
  }, [send]);

  const resume = useCallback(() => {
    recordersRef.current.forEach((recorder) => recorder.resume());
    setPaused(false);
    send({ type: "resume" });
  }, [send]);

  const end = useCallback(() => {
    stopRecorders();
    setPaused(false);
    setPhase("finalizing");
    setStatus("wrapping up");
    send({ type: "end" });
  }, [send, stopRecorders]);

  const reset = useCallback(() => {
    stopRecorders();
    setProposedNames([]);
    setCanReadScreen(false);
    import("../lib/nameDetection").then((m) => m.terminateWorker()).catch(() => {});
    socketRef.current?.close();
    socketRef.current = null;
    setPhase("idle");
    setMeetingId(null);
    setSegments([]);
    setCandidates([]);
    setWarnings([]);
    setStatus(null);
    setError(null);
    setPaused(false);
  }, [stopRecorders]);

  const value = useMemo(
    () => ({
      phase,
      active,
      isRunning: phase === "live",
      meetingId,
      roster,
      segments,
      candidates,
      warnings,
      status,
      error,
      engines,
      tracks,
      paused,
      barHidden,
      setBarHidden,
      proposedNames,
      scanning,
      canReadScreen,
      scanScreenForNames,
      confirmNames,
      dismissName,
      start,
      pause,
      resume,
      end,
      reset,
      send,
      setError,
      setWarnings,
    }),
    [
      phase, active, meetingId, roster, segments, candidates, warnings, status,
      error, engines, tracks, paused, barHidden, proposedNames, scanning, canReadScreen,
      scanScreenForNames, confirmNames, dismissName, start, pause, resume, end, reset, send,
    ]
  );

  return <LiveSessionContext.Provider value={value}>{children}</LiveSessionContext.Provider>;
}

export function useLiveSession() {
  const context = useContext(LiveSessionContext);
  if (!context) throw new Error("useLiveSession must be used inside <LiveSessionProvider>");
  return context;
}
