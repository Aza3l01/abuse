"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

interface MemberRow {
  id: string;
  client_id: string;
  email: string;
  full_name: string | null;
  role: string;
  is_billing_contact: boolean;
  created_at: string;
}

interface BillingNotifications {
  mode: "owner" | "selected" | "all";
  reminders_enabled: boolean;
}

interface InviteRow {
  id: string;
  invited_email: string;
  role: string;
  expires_at: string;
  expired: boolean;
  created_at: string;
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "7px 10px",
  fontSize: "13px",
  border: "1px solid var(--color-border)",
  background: "var(--color-surface)",
  color: "var(--color-text)",
  boxSizing: "border-box",
};

/**
 * Item 9's Team Members section: member list (role change / remove, owner
 * only) + invite form + pending invites (resend / cancel). Renders nothing
 * if the current role can't manage a team (403 from the list endpoints —
 * viewers never see this tab per item 8's RBAC, but the API is the real
 * enforcement boundary, not this check).
 */
export function TeamMembersSection({ myRole, onOwnershipTransferred }: { myRole: string | null; onOwnershipTransferred?: () => void }) {
  const [members,  setMembers]  = useState<MemberRow[] | null>(null);
  const [invites,   setInvites]  = useState<InviteRow[] | null>(null);
  const [loadError, setLoadError] = useState(false);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole,  setInviteRole]  = useState<"admin" | "viewer">("viewer");
  const [inviting,    setInviting]    = useState(false);
  const [inviteMsg,   setInviteMsg]   = useState<string | null>(null);
  const [inviteErr,   setInviteErr]   = useState<string | null>(null);

  // Item 40 follow-up: transfer ownership to an existing admin
  const [transferTarget, setTransferTarget] = useState<MemberRow | null>(null);
  const [transferring,   setTransferring]   = useState(false);
  const [transferError,  setTransferError]  = useState<string | null>(null);

  const isOwner = myRole === "owner";

  // Billing emails: who receives them and whether routine reminders are sent.
  // Owner only, the endpoint is 403 for everyone else.
  const [notif,       setNotif]       = useState<BillingNotifications | null>(null);
  const [notifSaving, setNotifSaving] = useState(false);
  const [notifErr,    setNotifErr]    = useState<string | null>(null);

  function loadNotifications() {
    if (!isOwner) return;
    apiFetch(`/billing/notifications`)
      .then(r => (r.ok ? r.json() : null))
      .then((n: BillingNotifications | null) => { if (n) setNotif(n); })
      .catch(() => {/* the settings stay hidden if they cannot load */});
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadNotifications(); }, [isOwner]);

  async function saveNotifications(next: BillingNotifications) {
    const previous = notif;
    setNotif(next);
    setNotifSaving(true);
    setNotifErr(null);
    try {
      const r = await apiFetch(`/billing/notifications`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(next),
      });
      if (!r.ok) {
        setNotif(previous);
        const d = await r.json().catch(() => ({}));
        setNotifErr(typeof d?.detail === "string" ? d.detail : "Could not save billing email settings.");
      }
    } catch {
      setNotif(previous);
      setNotifErr("Network error. Please try again.");
    } finally {
      setNotifSaving(false);
    }
  }

  async function handleBillingContact(memberId: string, value: boolean) {
    setNotifErr(null);
    const r = await apiFetch(`/org/members/${memberId}/billing-contact`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_billing_contact: value }),
    }).catch(() => null);
    if (!r || !r.ok) setNotifErr("Could not update the billing contact.");
    loadAll();
  }

  function loadAll() {
    Promise.all([
      apiFetch(`/org/members`),
      apiFetch(`/org/invites`),
    ])
      .then(async ([m, i]) => {
        if (!m.ok || !i.ok) { setLoadError(true); return; }
        setMembers(await m.json());
        setInvites(await i.json());
      })
      .catch(() => setLoadError(true));
  }

  useEffect(() => { loadAll(); }, []);

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    setInviting(true);
    setInviteErr(null);
    setInviteMsg(null);
    try {
      const r = await apiFetch(`/org/invite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        setInviteErr(typeof data?.detail === "string" ? data.detail : "Could not send invite.");
        return;
      }
      setInviteMsg("Invite sent.");
      setInviteEmail("");
      loadAll();
    } catch {
      setInviteErr("Network error. Please try again.");
    } finally {
      setInviting(false);
    }
  }

  async function handleRoleChange(memberId: string, role: string) {
    await apiFetch(`/org/members/${memberId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    loadAll();
  }

  async function handleRemoveMember(memberId: string) {
    await apiFetch(`/org/members/${memberId}`, {
      method: "DELETE",
    });
    loadAll();
  }

  async function handleResendInvite(inviteId: string) {
    await apiFetch(`/org/invites/${inviteId}/resend`, {
      method: "POST",
    });
    loadAll();
  }

  async function handleCancelInvite(inviteId: string) {
    await apiFetch(`/org/invites/${inviteId}`, {
      method: "DELETE",
    });
    loadAll();
  }

  async function handleTransferOwnership() {
    if (!transferTarget) return;
    setTransferring(true);
    setTransferError(null);
    try {
      const r = await apiFetch(`/org/members/${transferTarget.id}/transfer-ownership`, {
        method: "POST",
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setTransferError(d?.detail ?? "Could not transfer ownership.");
        return;
      }
      setTransferTarget(null);
      loadAll();
      onOwnershipTransferred?.();
    } catch {
      setTransferError("Network error. Please try again.");
    } finally {
      setTransferring(false);
    }
  }

  if (loadError || members === null) {
    return null;
  }

  return (
    <div style={{ border: "1px solid var(--color-border)", background: "var(--color-bg)" }}>
      <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
        <thead>
          <tr style={{ borderBottom: "1px solid var(--color-border)" }}>
            <th style={{ padding: "14px 20px", textAlign: "left", fontWeight: 500, color: "var(--color-text-muted)" }}>Name</th>
            <th style={{ padding: "14px 20px", textAlign: "left", fontWeight: 500, color: "var(--color-text-muted)" }}>Email</th>
            <th style={{ padding: "14px 20px", textAlign: "left", fontWeight: 500, color: "var(--color-text-muted)" }}>Role</th>
            <th style={{ padding: "14px 20px", textAlign: "left", fontWeight: 500, color: "var(--color-text-muted)" }}>Billing contact</th>
            {isOwner && <th style={{ padding: "14px 20px" }} />}
          </tr>
        </thead>
        <tbody>
          {members.map(m => (
            <tr key={m.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
              <td style={{ padding: "14px 20px" }}>{m.full_name || ""}</td>
              <td style={{ padding: "14px 20px" }}>{m.email}</td>
              <td style={{ padding: "14px 20px", textTransform: "capitalize" }}>
                {isOwner && m.role !== "owner" ? (
                  <select
                    value={m.role}
                    onChange={e => handleRoleChange(m.id, e.target.value)}
                    style={{ ...inputStyle, width: "auto", padding: "4px 8px" }}
                  >
                    <option value="admin">Admin</option>
                    <option value="viewer">Viewer</option>
                  </select>
                ) : (
                  m.role
                )}
              </td>
              <td style={{ padding: "14px 20px" }}>
                {isOwner ? (
                  <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "12px", cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={m.is_billing_contact}
                      onChange={e => handleBillingContact(m.id, e.target.checked)}
                    />
                    {m.is_billing_contact ? "Yes" : "No"}
                  </label>
                ) : (
                  <span style={{ color: "var(--color-text-muted)" }}>{m.is_billing_contact ? "Yes" : "No"}</span>
                )}
              </td>
              {isOwner && (
                <td style={{ padding: "14px 20px", textAlign: "right" }}>
                  {m.role === "admin" && (
                    <button
                      onClick={() => setTransferTarget(m)}
                      style={{
                        padding: "4px 10px", fontSize: "11px", marginRight: "8px",
                        border: "1px solid var(--color-border)",
                        background: "transparent", color: "var(--color-text)", cursor: "pointer",
                      }}
                    >
                      Make owner
                    </button>
                  )}
                  {m.role !== "owner" && (
                    <button
                      onClick={() => handleRemoveMember(m.id)}
                      style={{
                        padding: "4px 10px", fontSize: "11px",
                        border: "1px solid var(--color-critical)",
                        background: "transparent", color: "var(--color-critical)", cursor: "pointer",
                      }}
                    >
                      Remove
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      </div>

      {isOwner && notif && (
        <div style={{ borderTop: "1px solid var(--color-border)", padding: "18px 20px" }}>
          <p style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: "10px" }}>
            Billing emails
          </p>
          <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap", marginBottom: "10px" }}>
            <label style={{ fontSize: "12px", color: "var(--color-text-muted)" }} htmlFor="billing-email-mode">Send billing emails to</label>
            <select
              id="billing-email-mode"
              value={notif.mode}
              disabled={notifSaving}
              onChange={e => saveNotifications({ ...notif, mode: e.target.value as BillingNotifications["mode"] })}
              style={{ ...inputStyle, width: "auto", padding: "4px 8px" }}
            >
              <option value="owner">Owners only</option>
              <option value="selected">Members marked as billing contact</option>
              <option value="all">All members</option>
            </select>
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "12px", cursor: "pointer", marginBottom: "8px" }}>
            <input
              type="checkbox"
              checked={notif.reminders_enabled}
              disabled={notifSaving}
              onChange={e => saveNotifications({ ...notif, reminders_enabled: e.target.checked })}
            />
            Send routine billing reminders (upcoming bill, payment due)
          </label>
          <p style={{ fontSize: "11px", color: "var(--color-text-muted)", margin: 0, lineHeight: 1.5 }}>
            Payment receipts are always sent. The warning before a plan is cancelled and the cancellation notice always reach the owners.
          </p>
          {notifErr && (
            <p style={{ fontSize: "12px", color: "var(--color-critical)", marginTop: "8px" }}>{notifErr}</p>
          )}
        </div>
      )}

      {invites && invites.length > 0 && (
        <div style={{ borderTop: "1px solid var(--color-border)", padding: "18px 20px" }}>
          <p style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: "10px" }}>
            Pending invites
          </p>
          {invites.map(inv => (
            <div key={inv.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 0" }}>
              <span style={{ fontSize: "13px" }}>
                {inv.invited_email}{" "}
                <span style={{ color: "var(--color-text-muted)" }}>
                  ({inv.role}{inv.expired ? ", expired" : ""})
                </span>
              </span>
              <span style={{ display: "flex", gap: "8px" }}>
                <button
                  onClick={() => handleResendInvite(inv.id)}
                  style={{ padding: "4px 10px", fontSize: "11px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
                >
                  Resend
                </button>
                <button
                  onClick={() => handleCancelInvite(inv.id)}
                  style={{ padding: "4px 10px", fontSize: "11px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
                >
                  Cancel
                </button>
              </span>
            </div>
          ))}
        </div>
      )}

      <form onSubmit={handleInvite} style={{ borderTop: "1px solid var(--color-border)", padding: "18px 20px", display: "flex", gap: "8px", alignItems: "center" }}>
        <input
          type="email"
          required
          placeholder="teammate@yourcompany.com"
          value={inviteEmail}
          onChange={e => setInviteEmail(e.target.value)}
          style={{ ...inputStyle, flex: 1 }}
        />
        <select
          value={inviteRole}
          onChange={e => setInviteRole(e.target.value as "admin" | "viewer")}
          style={{ ...inputStyle, width: "auto" }}
        >
          <option value="viewer">Viewer</option>
          <option value="admin">Admin</option>
        </select>
        <button
          type="submit"
          disabled={inviting}
          style={{
            padding: "7px 16px", fontSize: "12px",
            border: "1px solid var(--color-text)",
            background: "var(--color-text)", color: "var(--color-bg)",
            cursor: inviting ? "default" : "pointer",
            opacity: inviting ? 0.6 : 1,
            whiteSpace: "nowrap",
          }}
        >
          {inviting ? "Sending…" : "Invite"}
        </button>
      </form>
      {(inviteMsg || inviteErr) && (
        <p style={{
          padding: "0 16px 14px",
          fontSize: "12px",
          color: inviteErr ? "var(--color-critical)" : "var(--color-low)",
        }}>
          {inviteErr ?? inviteMsg}
        </p>
      )}

      {/* Ownership transfer confirmation modal */}
      {transferTarget && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(13,13,13,0.6)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
        }}>
          <div style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)", padding: "24px", maxWidth: "420px", width: "90%", animation: "modal-panel-in 150ms ease-out" }}>
            <p style={{ fontSize: "14px", marginBottom: "16px", lineHeight: 1.5 }}>
              Make <strong>{transferTarget.email}</strong> the owner of this organisation?
            </p>
            <p style={{ fontSize: "12px", color: "var(--color-text-muted)", marginBottom: "20px", lineHeight: 1.5 }}>
              You will be demoted to Admin. Only the owner can manage billing, change member
              roles, or delete the organisation.
            </p>
            {transferError && (
              <p style={{ fontSize: "12px", color: "var(--color-critical)", marginBottom: "16px" }}>{transferError}</p>
            )}
            <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
              <button
                onClick={() => setTransferTarget(null)}
                style={{ padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text)", cursor: "pointer" }}
              >
                Cancel
              </button>
              <button
                onClick={handleTransferOwnership}
                disabled={transferring}
                style={{
                  padding: "7px 16px", fontSize: "12px", border: "1px solid var(--color-text)",
                  background: "var(--color-text)", color: "var(--color-bg)",
                  cursor: transferring ? "default" : "pointer", opacity: transferring ? 0.6 : 1,
                }}
              >
                {transferring ? "Working…" : "Confirm transfer"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
