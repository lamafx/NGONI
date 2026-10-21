import { Avatar } from "../ui/Avatar";
import { Icon } from "../ui/Icon";

export function MessageBubble({ message, agentName, userAvatar, onQuickReply, interactive = true }) {
  if (message.sender === "system") {
    return <div className="msg-divider">{message.text}</div>;
  }

  // Note interne : visible du conseiller seulement, jamais transmise au
  // client. Elle vit dans le fil (c'est la ou on la relit) mais doit se
  // distinguer d'une reponse au premier coup d'oeil.
  if (message.sender === "note") {
    return (
      <div className="msg-note">
        <div className="msg-note-head">
          <Icon name="note" size={13} /> Note interne · {message.authorName ?? "conseiller"}
        </div>
        <div className="msg-note-body">{message.text}</div>
        <div className="msg-note-time">{message.time}</div>
      </div>
    );
  }

  const isUser = message.sender === "user";
  const kind = message.sender === "agent" ? "agent" : message.sender === "ai" ? "ai" : "user";

  return (
    <div className={`msg-row ${isUser ? "from-user" : "from-ai"}`}>
      {/* La rangee est en `row-reverse` cote client (voir .msg-row.from-user) :
          la pastille se place d'elle-meme a droite. */}
      {/* Cote client, la pastille n'apparait que si l'appelant a fourni une
          photo : sans elle on retomberait sur un monogramme « U » anonyme,
          moins parlant que pas de pastille du tout. */}
      {(!isUser || userAvatar) && (
        <Avatar
          kind={isUser ? undefined : kind}
          name={isUser ? "" : agentName}
          src={isUser ? userAvatar : undefined}
          size={30}
        />
      )}
      <div>
        <div className="msg-bubble">
          {message.variant === "loading" && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <LoadingDots /> {message.text}
            </span>
          )}
          {message.variant === "success" && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "var(--good)" }}>
              <Icon name="check-circle" size={16} /> {message.text}
            </span>
          )}
          {message.variant === "error" && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "var(--risk)" }}>
              <Icon name="alert" size={16} /> {message.text}
            </span>
          )}
          {(!message.variant || message.variant === "verification" || message.variant === "default") && message.text}
        </div>
        {interactive && message.quickReplies && message.quickReplies.length > 0 && (
          <div className="quick-replies">
            {message.quickReplies.map((qr) => (
              <button key={qr.action} className="btn btn-secondary btn-sm" onClick={() => onQuickReply?.(qr.action, qr.label)}>
                {qr.label}
              </button>
            ))}
          </div>
        )}
        <div className="msg-meta">{message.time}</div>
      </div>
    </div>
  );
}

function LoadingDots() {
  return (
    <span style={{ display: "inline-flex", gap: 3 }}>
      <Dot delay={0} />
      <Dot delay={0.15} />
      <Dot delay={0.3} />
    </span>
  );
}

function Dot({ delay }) {
  return (
    <span
      style={{
        width: 5,
        height: 5,
        borderRadius: "50%",
        background: "var(--ink-faint)",
        display: "inline-block",
        animation: `pulse-dot 1s ${delay}s infinite ease-in-out`,
      }}
    />
  );
}
