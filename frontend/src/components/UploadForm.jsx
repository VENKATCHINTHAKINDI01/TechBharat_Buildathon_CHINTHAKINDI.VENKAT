import { useCallback, useRef, useState } from "react";
import { uploadMeeting } from "../api/client";
import { useToast } from "../ui/toast";

const DEFAULT_PARTICIPANTS = "Arjun\nRohit\nMeera\nPriya";

const TRANSCRIPT_EXT = ["txt", "vtt", "srt"];
const MEDIA_EXT = [
  "mp3", "wav", "m4a", "aac", "ogg", "oga", "opus", "flac", "wma",
  "mp4", "mov", "mkv", "avi", "webm", "m4v",
];
const ACCEPT = [...TRANSCRIPT_EXT, ...MEDIA_EXT].map((e) => `.${e}`).join(",");

function extensionOf(name = "") {
  return name.includes(".") ? name.split(".").pop().toLowerCase() : "";
}

function describe(file) {
  const extension = extensionOf(file.name);
  const megabytes = file.size / 1024 / 1024;
  return {
    extension,
    isMedia: MEDIA_EXT.includes(extension),
    isTranscript: TRANSCRIPT_EXT.includes(extension),
    size: megabytes < 1 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${megabytes.toFixed(1)} MB`,
    megabytes,
  };
}

export default function UploadForm({ onUploaded }) {
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("Sprint standup");
  const [meetingDate, setMeetingDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [participants, setParticipants] = useState(DEFAULT_PARTICIPANTS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);
  const toast = useToast();

  const info = file ? describe(file) : null;

  const accept = useCallback(
    (chosen) => {
      setError(null);
      if (!chosen) return;

      const details = describe(chosen);
      if (!details.isMedia && !details.isTranscript) {
        setError(
          `'.${details.extension}' isn't a format Nexvi.Meets can read. ` +
            "Transcripts: .txt, .vtt, .srt — Recordings: .mp3, .wav, .m4a, .mp4, .mov, .webm"
        );
        return;
      }
      const limit = details.isMedia ? 500 : 5;
      if (details.megabytes > limit) {
        setError(`That file is ${details.size}, over the ${limit}MB limit.`);
        return;
      }

      setFile(chosen);
      // Guess a title from the filename — almost always better than
      // "Sprint standup", and still editable.
      const stem = chosen.name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").trim();
      if (stem) setTitle(stem.charAt(0).toUpperCase() + stem.slice(1));
    },
    []
  );

  function onDrop(event) {
    event.preventDefault();
    setDragging(false);
    accept(event.dataTransfer.files?.[0] ?? null);
  }

  async function submit(event) {
    event.preventDefault();
    if (!file) {
      setError("Choose a transcript or a recording first.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const result = await uploadMeeting({ file, title, meetingDate, participants });
      if (result.source && result.source !== "transcript") {
        toast.info(
          "Recording transcribed",
          `${result.segments} segments via ${result.source}. Speech is unattributed until you say who spoke.`
        );
      } else {
        toast.success("Meeting analysed", `${result.candidates} commitment(s) found.`);
      }
      onUploaded(result);
    } catch (err) {
      setError(err.message);
      toast.error("Upload failed", err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2>Analyse a meeting</h2>

      {error && <div className="error">{error}</div>}

      <div
        className={`dropzone ${dragging ? "dragging" : ""} ${file ? "has-file" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
        aria-label="Choose a transcript or recording"
      >
        <div className="dz-icon" aria-hidden="true">{file ? (info.isMedia ? "♪" : "▤") : "↑"}</div>
        {file ? (
          <>
            <div className="dz-title">{file.name}</div>
            <div className="dz-hint">
              {info.size} · {info.isMedia ? "recording — will be transcribed" : "transcript"}
              {" · "}
              <span style={{ textDecoration: "underline" }}>choose another</span>
            </div>
          </>
        ) : (
          <>
            <div className="dz-title">Drop a file here, or click to browse</div>
            <div className="dz-hint">
              Transcripts: .txt .vtt .srt (up to 5MB)
              <br />
              Recordings: .mp3 .wav .m4a .mp4 .mov .webm (up to 500MB)
            </div>
          </>
        )}
        <input
          ref={inputRef}
          id="file"
          type="file"
          accept={ACCEPT}
          style={{ display: "none" }}
          onChange={(e) => accept(e.target.files?.[0] ?? null)}
        />
      </div>

      {info?.isMedia && (
        <div className="notice" style={{ marginTop: 16 }}>
          <strong>Recordings have no speaker labels.</strong> Speech-to-text returns words, not
          who said them, so every line arrives as <em>Unknown speaker</em> and nothing can be
          approved until you say who spoke. You do that on the next screen in one click per
          voice — Naina will not guess, because a guessed owner is exactly what the safety gate
          exists to prevent.
        </div>
      )}

      <div className="row" style={{ marginTop: 16 }}>
        <div className="field">
          <label htmlFor="title">Meeting title</label>
          <input id="title" value={title} onChange={(e) => setTitle(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="date">Meeting date</label>
          <input
            id="date"
            type="date"
            value={meetingDate}
            onChange={(e) => setMeetingDate(e.target.value)}
            required
          />
        </div>
      </div>

      <div className="field">
        <label htmlFor="participants">
          Participants — one per line as <code>Name &lt;email&gt;</code>, or a JSON array
        </label>
        <textarea
          id="participants"
          value={participants}
          onChange={(e) => setParticipants(e.target.value)}
        />
        <p className="muted" style={{ marginTop: 6 }}>
          Owner resolution fails closed: a name that isn’t in this list, or one that matches two
          people, resolves to nothing rather than being guessed.
        </p>
      </div>

      <div className="actions">
        <button className="primary" type="submit" disabled={busy || !file}>
          {busy ? (info?.isMedia ? "Transcribing…" : "Analysing…") : "Analyse meeting"}
        </button>
        {file && !busy && (
          <button type="button" className="ghost" onClick={() => setFile(null)}>
            Clear
          </button>
        )}
      </div>

      {busy && (
        <>
          <div className="progress">
            {/* Indeterminate on purpose: the server does not stream
                progress, and a fake percentage that sticks at 90% is
                worse than an honest "still working". */}
            <div className="progress-bar indeterminate" />
          </div>
          <p className="muted" style={{ marginTop: 8 }}>
            {info?.isMedia
              ? "Decoding audio and transcribing. A 45-minute recording takes a minute or two."
              : "Extracting commitments and running the safety gate."}
          </p>
        </>
      )}
    </form>
  );
}
