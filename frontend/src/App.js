import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { Activity, ArrowUpRight, Bell, CalendarDays, Check, ChevronRight, CircleDollarSign, ClipboardList, FileText, LayoutDashboard, LogOut, Menu, MessageSquare, Plus, RefreshCw, Search, Settings, ShieldCheck, Users, Wallet, X } from "lucide-react";
import "@/App.css";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const api = axios.create({ baseURL: API, withCredentials: true });

const statusMeta = { ACTIVE: ["Active", "good"], EXPIRING_SOON: ["Expiring", "warn"], GRACE_PERIOD: ["Grace period", "warn"], EXPIRED: ["Expired", "warn"], CANCELLED: ["Cancelled", "bad"], PERMANENTLY_DELETED: ["Erased", "bad"] };
const money = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;
const dateLabel = (value) => value ? new Date(value).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";
const initials = (name) => (name || "?").split(" ").map((x) => x[0]).join("").slice(0, 2).toUpperCase();

function StatusPill({ status }) { const [label, tone] = statusMeta[status] || [status, "neutral"]; return <span data-testid={`status-${String(status).toLowerCase()}`} className={`status-pill ${tone}`}><i />{label}</span>; }
function Empty({ text }) { return <div data-testid="empty-state" className="empty-state">{text}</div>; }

/* -------- Admin login -------- */
function Login({ onLogin, onMember }) {
  const [email, setEmail] = useState("admin@titangym.in");
  const [password, setPassword] = useState("Titan@123");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const submit = async (event) => {
    event.preventDefault(); setLoading(true); setError("");
    try { const result = await api.post("/auth/login", { email, password }); onLogin(result.data.user); }
    catch (err) { setError(err.response?.data?.detail || "Could not sign you in"); }
    finally { setLoading(false); }
  };
  return <main className="login-shell">
    <div className="login-visual"><div className="brand-mark">T<span>G</span></div><p className="eyebrow">PERFORMANCE OPERATING SYSTEM</p><h1>Train hard.<br /><em>Run smarter.</em></h1><p className="login-copy">The command centre for gyms that take every member seriously.</p><div className="login-stat"><strong>94.8%</strong><span>member retention<br />this month</span></div></div>
    <div className="login-panel">
      <div className="mobile-brand">TITANGYM <span>OS</span></div>
      <p className="eyebrow">STAFF ACCESS</p><h2>Welcome back.</h2><p className="muted">Sign in to your gym command centre.</p>
      <form onSubmit={submit} className="login-form">
        <label>Email address<input data-testid="login-email-input" value={email} onChange={(e) => setEmail(e.target.value)} type="email" required /></label>
        <label>Password<input data-testid="login-password-input" value={password} onChange={(e) => setPassword(e.target.value)} type="password" required /></label>
        {error && <div data-testid="login-error" className="form-error">{error}</div>}
        <button data-testid="login-submit-button" className="primary-button wide" disabled={loading}>{loading ? "Signing in…" : "Enter TitanGym"}<ArrowUpRight size={17} /></button>
      </form>
      <div className="login-foot"><ShieldCheck size={15} /> Secure staff session</div>
      <button data-testid="open-member-login-button" className="text-button member-switch" onClick={onMember}>I'm a member — open member portal <ArrowUpRight size={14} /></button>
    </div>
  </main>;
}

/* -------- Member OTP flow -------- */
function MemberLogin({ onMemberLogin, onBack }) {
  const [phone, setPhone] = useState("+91 98111 22031");
  const [otp, setOtp] = useState("");
  const [step, setStep] = useState("phone");
  const [error, setError] = useState("");
  const [devOtp, setDevOtp] = useState("");
  const [loading, setLoading] = useState(false);
  const requestOtp = async (e) => {
    e.preventDefault(); setLoading(true); setError("");
    try { const r = await api.post("/auth/member/request-otp", { phone }); setStep("otp"); if (r.data.development_otp) setDevOtp(r.data.development_otp); }
    catch (err) { setError(err.response?.data?.detail || "Could not send OTP"); }
    finally { setLoading(false); }
  };
  const verifyOtp = async (e) => {
    e.preventDefault(); setLoading(true); setError("");
    try { const r = await api.post("/auth/member/verify-otp", { phone, otp }); onMemberLogin(r.data.member); }
    catch (err) { setError(err.response?.data?.detail || "Invalid or expired OTP"); }
    finally { setLoading(false); }
  };
  return <main className="member-login">
    <div className="member-login-panel">
      <div className="member-login-brand">TITANGYM <span>OS</span></div>
      <p className="eyebrow">MEMBER PORTAL</p>
      <h2>Your training,<br /><em>your account.</em></h2>
      <p className="muted">Sign in with your registered phone to view your membership.</p>
      {step === "phone" ? (
        <form onSubmit={requestOtp} className="login-form">
          <label>Registered phone<input data-testid="member-phone-input" value={phone} onChange={(e) => setPhone(e.target.value)} required /></label>
          {error && <div data-testid="member-login-error" className="form-error">{error}</div>}
          <button data-testid="member-request-otp-button" className="primary-button wide" disabled={loading}>{loading ? "Sending…" : "Send OTP"}<ArrowUpRight size={17} /></button>
        </form>
      ) : (
        <form onSubmit={verifyOtp} className="login-form">
          <label>One-time password<input data-testid="member-otp-input" value={otp} onChange={(e) => setOtp(e.target.value)} maxLength={6} required autoFocus /></label>
          {devOtp && <div className="provider-note" data-testid="member-dev-otp-hint"><MessageSquare size={14} /> Development OTP: <b>{devOtp}</b></div>}
          {error && <div data-testid="member-login-error" className="form-error">{error}</div>}
          <button data-testid="member-verify-otp-button" className="primary-button wide" disabled={loading}>{loading ? "Verifying…" : "Verify & continue"}<ArrowUpRight size={17} /></button>
          <button data-testid="member-change-phone-button" type="button" className="text-button" onClick={() => { setStep("phone"); setOtp(""); setError(""); }}>Use a different phone</button>
        </form>
      )}
      <button data-testid="back-to-admin-login-button" className="text-button member-switch" onClick={onBack}>Back to staff sign-in</button>
    </div>
  </main>;
}

/* -------- Member portal (real data) -------- */
function MemberPortal({ onExit }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.get("/member/me")
      .then((r) => setData(r.data))
      .catch((err) => { if (err.response?.status === 401 || err.response?.status === 404) onExit(); else setError(err.response?.data?.detail || "Could not load your membership"); });
  }, [onExit]);
  const logout = async () => { await api.post("/auth/member/logout").catch(() => {}); onExit(); };
  if (error) return <main className="member-portal"><div className="member-wrap"><Empty text={error} /></div></main>;
  if (!data) return <main className="member-portal"><div className="member-wrap"><Empty text="Loading your membership…" /></div></main>;
  const { member, plan, gym, history, payments, days_remaining } = data;
  const paid = payments?.reduce((sum, p) => p.status === "PAID" ? sum + Number(p.amount || 0) : sum, 0) || 0;
  return <main className="member-portal">
    <div className="member-nav"><div className="brand-mark small">T<span>G</span></div><button data-testid="member-logout-button" className="ghost-button" onClick={logout}><LogOut size={15} /> Sign out</button></div>
    <div className="member-wrap">
      <div className="member-welcome"><p className="eyebrow">{(gym?.name || "TITANGYM").toUpperCase()}</p><h1>Your training<br /><em>doesn't stop.</em></h1><p>Hello {member.full_name?.split(" ")[0]}, here's where your membership stands today.</p></div>
      <section data-testid="member-status-card" className="member-status-card">
        <div className="status-card-top"><span className="eyebrow">CURRENT MEMBERSHIP</span><StatusPill status={member.status} /></div>
        <div className="member-profile"><div className="profile-photo">{initials(member.full_name)}</div><div><h2 data-testid="member-full-name">{member.full_name}</h2><span>{plan?.name || "Custom plan"}</span></div></div>
        <div className="member-dates">
          <div><small>Start</small><strong data-testid="member-start-date">{dateLabel(member.start_date)}</strong></div>
          <div><small>Expires</small><strong data-testid="member-expiry-date">{dateLabel(member.expiry_date)}</strong></div>
          <div><small>Days remaining</small><strong data-testid="member-days-remaining">{days_remaining ?? "—"}</strong></div>
        </div>
        <div className="member-cta-row">
          <div className="paid-summary"><small>Paid to date</small><strong>{money(paid)}</strong></div>
          <span className="renewal-note" data-testid="member-renewal-note">Contact the gym to renew your membership</span>
        </div>
      </section>
      <div className="member-bottom">
        <article className="panel"><p className="eyebrow">MEMBERSHIP HISTORY</p><h3>Your journey so far</h3>
          <div className="timeline">{history?.length ? history.map((h) => <div key={h.id} data-testid={`member-history-${h.id}`}><i /><span><strong>{h.type?.replaceAll("_", " ")}</strong><small>{dateLabel(h.created_at)} · {h.plan_name} · {money(h.amount)}</small></span></div>) : <Empty text="History will appear here." />}</div>
        </article>
        <article className="panel"><p className="eyebrow">RECENT PAYMENTS</p><h3>Payment history</h3>
          <div className="timeline">{payments?.length ? payments.slice(0, 5).map((p) => <div key={p.id} data-testid={`member-payment-${p.id}`}><i /><span><strong>{money(p.amount)} · {p.method}</strong><small>{dateLabel(p.created_at)} · {p.status}</small></span></div>) : <Empty text="No payments recorded yet." />}</div>
        </article>
      </div>
    </div>
  </main>;
}

/* -------- Admin app -------- */
function Sidebar({ page, setPage, onLogout, collapsed, setCollapsed, notificationCount }) {
  const links = [
    ["overview", "Overview", LayoutDashboard],
    ["members", "Members", Users],
    ["plans", "Membership plans", CalendarDays],
    ["payments", "Payments", Wallet],
    ["reports", "Reports", FileText],
    ["notifications", "Notifications", Bell],
    ["audit", "Audit log", ClipboardList],
    ["settings", "Gym settings", Settings],
  ];
  return <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
    <div className="side-top"><div className="brand-mark small">T<span>G</span></div><button data-testid="sidebar-collapse-button" className="icon-button" onClick={() => setCollapsed(!collapsed)} aria-label="Toggle sidebar"><Menu size={19} /></button></div>
    <div className="side-label">WORKSPACE</div>
    <nav>{links.map(([id, label, Icon]) => <button data-testid={`nav-${id}-button`} key={id} className={page === id ? "active" : ""} onClick={() => setPage(id)}><Icon size={18} /><span>{label}</span>{id === "notifications" && notificationCount > 0 && <b>{notificationCount}</b>}</button>)}</nav>
    <div className="side-bottom">
      <div className="provider-state"><span className="live-dot" /><div><strong>Scheduler live</strong><small>Daily lifecycle · Asia/Kolkata</small></div></div>
      <button data-testid="logout-button" className="logout-button" onClick={onLogout}><LogOut size={17} /><span>Sign out</span></button>
    </div>
  </aside>;
}

function Topbar({ page, onMember, onRunJobs, running }) {
  const titles = {
    overview: ["Good morning, Arjun", "Here's the pulse of your floor today."],
    members: ["Members", "Manage the people who power your gym."],
    plans: ["Membership plans", "Shape the offers that keep members moving."],
    payments: ["Payments", "Every rupee, accounted for."],
    reports: ["Reports", "A clearer view of momentum and revenue."],
    notifications: ["Notification centre", "Every message, accounted for."],
    audit: ["Audit log", "A trace of every important action."],
    settings: ["Gym settings", "Tune the operating rules for TitanGym."],
  };
  return <header className="topbar">
    <div><p className="eyebrow">TITANGYM OS · ADMIN</p><h1 data-testid="page-title">{titles[page][0]}</h1><p className="muted">{titles[page][1]}</p></div>
    <div className="top-actions">
      <button data-testid="run-lifecycle-button" className="ghost-button" onClick={onRunJobs} disabled={running}><RefreshCw size={15} className={running ? "spin" : ""} /> {running ? "Running…" : "Run lifecycle"}</button>
      <button data-testid="member-portal-button" className="ghost-button" onClick={onMember}><Activity size={16} /> Member portal</button>
      <div data-testid="admin-avatar" className="avatar">AM</div>
    </div>
  </header>;
}

function MetricCard({ label, value, note, tone, icon: Icon }) { return <article data-testid={`metric-${label.toLowerCase().replaceAll(" ", "-")}`} className={`metric-card ${tone || ""}`}><div className="metric-head"><span>{label}</span><Icon size={17} /></div><strong>{value}</strong><small>{note}</small></article>; }

function Overview({ data, setPage }) {
  const members = data?.members || [];
  const expiring = members.filter((m) => m.status === "EXPIRING_SOON");
  const grace = members.filter((m) => m.status === "GRACE_PERIOD");
  return <div className="page-content overview-page">
    <section className="metric-grid">
      <MetricCard label="Total members" value={data?.total_members || 0} note="Active roster excluding erased records" icon={Users} />
      <MetricCard label="Active members" value={data?.active_members || 0} note="Currently in good standing" tone="red" icon={Activity} />
      <MetricCard label="Expiring soon" value={data?.expiring_soon || 0} note="Within reminder window" tone="amber" icon={CalendarDays} />
      <MetricCard label="Revenue" value={money(data?.revenue)} note="Total collected (paid)" tone="blue" icon={CircleDollarSign} />
    </section>
    <section className="dashboard-grid">
      <article className="panel chart-panel"><div className="panel-heading"><div><p className="eyebrow">MEMBER MOMENTUM</p><h2>Status distribution</h2></div><span className="range-chip">Live <ChevronRight size={14} /></span></div>
        <div className="status-bars">
          {[["Active", data?.active_members || 0, "red"], ["Expiring soon", data?.expiring_soon || 0, "yellow"], ["Grace period", data?.grace_period || 0, "blue"], ["Cancelled", data?.cancelled || 0, "gray"]].map(([label, val, tone]) => (
            <div className="bar-row" key={label}><span>{label}</span><div><i className={tone} style={{ width: `${Math.max(6, Number(val) * 12)}%` }} /></div><b>{val}</b></div>
          ))}
        </div>
      </article>
      <article className="panel list-panel"><div className="panel-heading"><div><p className="eyebrow">GRACE PERIOD</p><h2>Bring them back</h2></div><span className="count-badge">{grace.length} members</span></div>{grace.length ? grace.map((m) => <MemberRow key={m.id} member={m} action="Contact" />) : <Empty text="No members in grace period." />}</article>
    </section>
    <section className="dashboard-grid lower-grid">
      <article className="panel list-panel"><div className="panel-heading"><div><p className="eyebrow">ATTENTION NEEDED</p><h2>Expiring soon</h2></div><button data-testid="view-members-button" className="text-button" onClick={() => setPage("members")}>View all <ArrowUpRight size={15} /></button></div>{expiring.length ? expiring.map((m) => <MemberRow key={m.id} member={m} action="Renew" />) : <Empty text="No members are expiring soon." />}</article>
    </section>
  </div>;
}

function MemberRow({ member, action }) { return <div data-testid={`member-row-${member.id}`} className="member-row"><div className="member-avatar">{initials(member.full_name)}</div><div className="member-row-main"><strong>{member.full_name}</strong><span>{member.phone}</span></div><div className="member-expiry"><small>{action === "Renew" ? "Expires" : "Grace ends"}</small><strong>{dateLabel(action === "Renew" ? member.expiry_date : member.grace_period_end)}</strong></div></div>; }

function Members({ members, plans, refresh }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("ALL");
  const [showAdd, setShowAdd] = useState(false);
  const [detail, setDetail] = useState(null);
  const filtered = members.filter((m) => (!search || `${m.full_name} ${m.phone}`.toLowerCase().includes(search.toLowerCase())) && (status === "ALL" || m.status === status));
  const openDetail = async (id) => { try { const r = await api.get(`/members/${id}`); setDetail(r.data); } catch { setDetail(null); } };
  return <div className="page-content">
    <div className="toolbar">
      <div className="search-wrap"><Search size={17} /><input data-testid="member-search-input" placeholder="Search name or phone" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
      <select data-testid="member-status-filter" value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="ALL">All statuses</option><option value="ACTIVE">Active</option><option value="EXPIRING_SOON">Expiring soon</option><option value="GRACE_PERIOD">Grace period</option><option value="CANCELLED">Cancelled</option>
      </select>
      <a data-testid="export-members-button" className="ghost-button" href={`${API}/members/export/csv`} target="_blank" rel="noreferrer"><FileText size={16} /> Export CSV</a>
      <button data-testid="add-member-button" className="primary-button" onClick={() => setShowAdd(true)}><Plus size={17} /> Add member</button>
    </div>
    <div className="panel table-panel">
      <div className="table-caption"><div><p className="eyebrow">DIRECTORY</p><h2>All members <span>{filtered.length}</span></h2></div></div>
      <div className="table-scroll"><table><thead><tr><th>Member</th><th>Plan</th><th>Membership window</th><th>Status</th><th>Payment</th><th /></tr></thead>
        <tbody>{filtered.map((m) => <tr data-testid={`member-table-row-${m.id}`} key={m.id}>
          <td><div className="table-member"><div className="member-avatar">{initials(m.full_name)}</div><div><strong>{m.full_name}</strong><small>{m.phone}</small></div></div></td>
          <td>{m.plan_name || plans.find((p) => p.id === m.plan_id)?.name || "Custom"}</td>
          <td><strong>{dateLabel(m.start_date)}</strong><small>to {dateLabel(m.expiry_date)}</small></td>
          <td><StatusPill status={m.status} /></td>
          <td><span className={`payment ${m.payment_status === "PAID" ? "paid" : "pending"}`}>{m.payment_status === "PAID" ? <Check size={13} /> : <CircleDollarSign size={13} />}{m.payment_status}</span></td>
          <td><button data-testid={`member-more-${m.id}-button`} className="icon-button" onClick={() => openDetail(m.id)}><ChevronRight size={17} /></button></td>
        </tr>)}</tbody>
      </table>{!filtered.length && <Empty text="No members match your filters." />}</div>
    </div>
    {showAdd && <AddMemberModal plans={plans} onClose={() => setShowAdd(false)} onSaved={() => { setShowAdd(false); refresh(); }} />}
    {detail && <MemberDetail detail={detail} plans={plans} onClose={() => setDetail(null)} refresh={() => { refresh(); openDetail(detail.member.id); }} />}
  </div>;
}

function AddMemberModal({ plans, onClose, onSaved }) {
  const [form, setForm] = useState({ full_name: "", phone: "", address: "", plan_id: plans[0]?.id || "", start_date: new Date().toISOString().slice(0, 10), payment_amount: plans[0]?.price || 0, payment_status: "PAID", payment_method: "UPI", notes: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const update = (key, value) => setForm({ ...form, [key]: value });
  const submit = async (e) => {
    e.preventDefault(); setSaving(true); setError("");
    try { await api.post("/members", { ...form, payment_amount: Number(form.payment_amount) }); onSaved(); }
    catch (err) { setError(err.response?.data?.detail || "Could not create member"); }
    finally { setSaving(false); }
  };
  return <div className="modal-backdrop"><form data-testid="add-member-modal" className="modal" onSubmit={submit}>
    <div className="modal-head"><div><p className="eyebrow">NEW REGISTRATION</p><h2>Add a member</h2></div><button data-testid="close-add-member-button" type="button" className="icon-button" onClick={onClose}><X size={18} /></button></div>
    <div className="form-grid">
      <label>Full name<input data-testid="member-full-name-input" required value={form.full_name} onChange={(e) => update("full_name", e.target.value)} /></label>
      <label>Phone number<input data-testid="member-phone-input" required value={form.phone} onChange={(e) => update("phone", e.target.value)} /></label>
      <label>Address<input data-testid="member-address-input" value={form.address} onChange={(e) => update("address", e.target.value)} /></label>
      <label>Start date<input data-testid="member-start-date-input" type="date" required value={form.start_date} onChange={(e) => update("start_date", e.target.value)} /></label>
      <label>Membership plan<select data-testid="member-plan-select" value={form.plan_id} onChange={(e) => { update("plan_id", e.target.value); update("payment_amount", plans.find((p) => p.id === e.target.value)?.price || 0); }}>{plans.map((p) => <option key={p.id} value={p.id}>{p.name} · {money(p.price)}</option>)}</select></label>
      <label>Payment method<select data-testid="member-payment-method-select" value={form.payment_method} onChange={(e) => update("payment_method", e.target.value)}><option>UPI</option><option>Cash</option><option>Card</option><option>Bank transfer</option></select></label>
      <label>Amount paid<input data-testid="member-payment-amount-input" type="number" value={form.payment_amount} onChange={(e) => update("payment_amount", e.target.value)} /></label>
      <label>Payment status<select data-testid="member-payment-status-select" value={form.payment_status} onChange={(e) => update("payment_status", e.target.value)}><option>PAID</option><option>PENDING</option><option>PARTIAL</option></select></label>
    </div>
    {error && <div data-testid="add-member-error" className="form-error">{error}</div>}
    <div className="modal-foot"><span className="provider-note"><MessageSquare size={15} /> Welcome message queued · WhatsApp disabled</span><button data-testid="save-member-button" className="primary-button" disabled={saving}>{saving ? "Saving…" : "Create member"}</button></div>
  </form></div>;
}

function MemberDetail({ detail, plans, onClose, refresh }) {
  const { member, plan, history, notifications, payments, audit } = detail;
  const [tab, setTab] = useState("membership");
  const [showRenew, setShowRenew] = useState(false);
  const cancel = async () => { if (!window.confirm("Cancel this membership immediately?")) return; await api.post(`/members/${member.id}/cancel`); refresh(); };
  return <div className="modal-backdrop"><div data-testid="member-detail-modal" className="modal detail">
    <div className="modal-head">
      <div><p className="eyebrow">MEMBER PROFILE</p><h2>{member.full_name}</h2><span className="muted">{member.phone}</span></div>
      <button data-testid="close-detail-button" className="icon-button" onClick={onClose}><X size={18} /></button>
    </div>
    <div className="detail-summary">
      <div><small>Status</small><StatusPill status={member.status} /></div>
      <div><small>Plan</small><strong>{plan?.name || "Custom"}</strong></div>
      <div><small>Expires</small><strong>{dateLabel(member.expiry_date)}</strong></div>
      <div><small>Payment</small><strong>{member.payment_status}</strong></div>
    </div>
    <div className="detail-actions">
      <button data-testid="open-renew-button" className="primary-button" onClick={() => setShowRenew(true)}><RefreshCw size={15} /> Renew</button>
      {member.status !== "CANCELLED" && member.status !== "PERMANENTLY_DELETED" && <button data-testid="cancel-membership-button" className="ghost-button" onClick={cancel}>Cancel membership</button>}
    </div>
    <div className="detail-tabs">
      {["membership", "payments", "notifications", "audit"].map((id) => <button key={id} data-testid={`detail-tab-${id}`} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{id.charAt(0).toUpperCase() + id.slice(1)}</button>)}
    </div>
    <div className="detail-body">
      {tab === "membership" && (history?.length ? history.map((h) => <div key={h.id} className="detail-row"><strong>{h.type?.replaceAll("_", " ")}</strong><span>{h.plan_name} · {dateLabel(h.start_date)} → {dateLabel(h.expiry_date)} · {money(h.amount)}</span></div>) : <Empty text="No membership history yet." />)}
      {tab === "payments" && (payments?.length ? payments.map((p) => <div key={p.id} className="detail-row"><strong>{money(p.amount)} · {p.method}</strong><span>{dateLabel(p.created_at)} · {p.status}</span></div>) : <Empty text="No payments recorded." />)}
      {tab === "notifications" && (notifications?.length ? notifications.map((n) => <div key={n.id} className="detail-row"><strong>{n.type?.replaceAll("_", " ")}</strong><span>{n.status} · {dateLabel(n.created_at)}</span></div>) : <Empty text="No notifications sent yet." />)}
      {tab === "audit" && (audit?.length ? audit.map((a) => <div key={a.id} className="detail-row"><strong>{a.action}</strong><span>{a.actor_role || "SYSTEM"} · {dateLabel(a.created_at)}</span></div>) : <Empty text="No audit entries yet." />)}
    </div>
    {showRenew && <RenewModal member={member} plans={plans} onClose={() => setShowRenew(false)} onSaved={() => { setShowRenew(false); refresh(); }} />}
  </div></div>;
}

function RenewModal({ member, plans, onClose, onSaved }) {
  const [form, setForm] = useState({ plan_id: member.plan_id || plans[0]?.id, start_date: new Date().toISOString().slice(0, 10), payment_amount: plans.find((p) => p.id === member.plan_id)?.price || 0, payment_method: "UPI", payment_status: "PAID" });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const submit = async (e) => {
    e.preventDefault(); setSaving(true); setError("");
    try { await api.post(`/members/${member.id}/renew`, { ...form, payment_amount: Number(form.payment_amount) }); onSaved(); }
    catch (err) { setError(err.response?.data?.detail || "Could not renew"); }
    finally { setSaving(false); }
  };
  return <div className="modal-backdrop"><form data-testid="renew-modal" className="modal compact" onSubmit={submit}>
    <div className="modal-head"><div><p className="eyebrow">RENEWAL</p><h2>Renew {member.full_name}</h2></div><button data-testid="close-renew-button" type="button" className="icon-button" onClick={onClose}><X size={18} /></button></div>
    <div className="form-grid">
      <label>Plan<select data-testid="renew-plan-select" value={form.plan_id} onChange={(e) => { const p = plans.find((x) => x.id === e.target.value); setForm({ ...form, plan_id: e.target.value, payment_amount: p?.price || 0 }); }}>{plans.map((p) => <option key={p.id} value={p.id}>{p.name} · {money(p.price)}</option>)}</select></label>
      <label>Start date<input data-testid="renew-start-input" type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} /></label>
      <label>Amount<input data-testid="renew-amount-input" type="number" value={form.payment_amount} onChange={(e) => setForm({ ...form, payment_amount: e.target.value })} /></label>
      <label>Method<select data-testid="renew-method-select" value={form.payment_method} onChange={(e) => setForm({ ...form, payment_method: e.target.value })}><option>UPI</option><option>Cash</option><option>Card</option><option>Bank transfer</option></select></label>
    </div>
    {error && <div data-testid="renew-error" className="form-error">{error}</div>}
    <div className="modal-foot"><button data-testid="submit-renew-button" className="primary-button" disabled={saving}>{saving ? "Renewing…" : "Confirm renewal"}</button></div>
  </form></div>;
}

function Plans({ plans, refresh }) {
  const [show, setShow] = useState(false);
  return <div className="page-content">
    <div className="toolbar"><div><p className="eyebrow">OFFER ARCHITECTURE</p><h2 className="section-title">Plans that earn commitment.</h2></div><button data-testid="create-plan-button" className="primary-button" onClick={() => setShow(true)}><Plus size={17} /> Create plan</button></div>
    <div className="plan-grid">{plans.map((p, i) => <article data-testid={`plan-card-${p.id}`} className="plan-card" key={p.id}><div className="plan-index">0{i + 1}</div><div className="plan-icon"><Activity size={20} /></div><h3>{p.name}</h3><p>{p.description}</p><strong>{money(p.price)}<small> / {p.duration_months} {p.duration_months === 1 ? "month" : "months"}</small></strong><div className="plan-footer"><span className="active-label"><i /> {p.active ? "Active" : "Inactive"}</span></div></article>)}</div>
    {show && <PlanModal onClose={() => setShow(false)} onSaved={() => { setShow(false); refresh(); }} />}
  </div>;
}

function PlanModal({ onClose, onSaved }) {
  const [form, setForm] = useState({ name: "", duration_months: 1, price: 0, description: "" });
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    try { await api.post("/plans", { ...form, duration_months: Number(form.duration_months), price: Number(form.price) }); onSaved(); }
    catch (err) { setError(err.response?.data?.detail || "Could not save plan"); }
  };
  return <div className="modal-backdrop"><form data-testid="create-plan-modal" className="modal compact" onSubmit={submit}>
    <div className="modal-head"><div><p className="eyebrow">PLAN BUILDER</p><h2>Create a plan</h2></div><button data-testid="close-plan-modal-button" type="button" className="icon-button" onClick={onClose}><X size={18} /></button></div>
    <label>Plan name<input data-testid="plan-name-input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
    <div className="form-grid">
      <label>Duration (months)<input data-testid="plan-duration-input" type="number" min="1" value={form.duration_months} onChange={(e) => setForm({ ...form, duration_months: e.target.value })} /></label>
      <label>Price<input data-testid="plan-price-input" type="number" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} /></label>
    </div>
    <label>Description<textarea data-testid="plan-description-input" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
    {error && <div data-testid="plan-error" className="form-error">{error}</div>}
    <div className="modal-foot"><button data-testid="save-plan-button" className="primary-button">Save plan</button></div>
  </form></div>;
}

function Payments() {
  const [payments, setPayments] = useState([]);
  const load = () => api.get("/payments").then((r) => setPayments(r.data));
  useEffect(() => { load(); }, []);
  const total = payments.reduce((sum, p) => p.status === "PAID" ? sum + Number(p.amount || 0) : sum, 0);
  return <div className="page-content">
    <section className="report-hero"><div><p className="eyebrow">CASH LEDGER</p><h2>Payments recorded</h2><p>Every membership fee, tracked and receipt-ready.</p></div><div className="report-total"><span>Collected (paid)</span><strong data-testid="payments-total">{money(total)}</strong><small>Across all recorded payments</small></div></section>
    <div className="panel table-panel"><div className="table-caption"><div><p className="eyebrow">RECEIPTS</p><h2>All payments <span>{payments.length}</span></h2></div></div>
      <div className="table-scroll"><table><thead><tr><th>Member</th><th>Amount</th><th>Method</th><th>Status</th><th>Date</th><th /></tr></thead>
        <tbody>{payments.map((p) => <tr key={p.id} data-testid={`payment-row-${p.id}`}>
          <td>{p.member_id}</td><td><strong>{money(p.amount)}</strong></td><td>{p.method}</td>
          <td><span className={`payment ${p.status === "PAID" ? "paid" : "pending"}`}>{p.status}</span></td>
          <td>{dateLabel(p.created_at)}</td>
          <td><a data-testid={`receipt-${p.id}-link`} className="text-button" href={`${API}/payments/${p.id}/receipt`} target="_blank" rel="noreferrer">Receipt <ArrowUpRight size={13} /></a></td>
        </tr>)}</tbody>
      </table>{!payments.length && <Empty text="No payments recorded yet." />}</div>
    </div>
  </div>;
}

function Reports({ data }) {
  const [summary, setSummary] = useState(null);
  useEffect(() => { api.get("/reports/summary").then((r) => setSummary(r.data)); }, []);
  return <div className="page-content">
    <section className="report-hero"><div><p className="eyebrow">MONTHLY SNAPSHOT</p><h2>Revenue & retention</h2><p>This month vs. last month, with a live look at where your members are in their journey.</p></div><div className="report-total"><span>This month</span><strong data-testid="report-this-month">{money(summary?.revenue_this_month)}</strong><small>Last month: {money(summary?.revenue_last_month)}</small></div></section>
    <div className="report-grid">
      <article className="panel report-card"><p className="eyebrow">STATUS BREAKDOWN</p><h3>Member health</h3>{[["Active", data?.active_members || 0, "red"], ["Expiring soon", data?.expiring_soon || 0, "yellow"], ["Grace period", data?.grace_period || 0, "blue"], ["Cancelled", data?.cancelled || 0, "gray"]].map(([label, value, tone]) => <div className="bar-row" key={label}><span>{label}</span><div><i className={tone} style={{ width: `${Math.max(8, Number(value) * 12)}%` }} /></div><b>{value}</b></div>)}</article>
      <article className="panel report-card"><p className="eyebrow">PLAN DISTRIBUTION</p><h3>Where members land</h3>{summary?.plan_distribution?.map((p) => <div className="bar-row" key={p.plan_id}><span>{p.name}</span><div><i className="red" style={{ width: `${Math.max(8, p.count * 12)}%` }} /></div><b>{p.count}</b></div>) || <Empty text="Loading…" />}</article>
    </div>
    <article className="panel report-card"><p className="eyebrow">CASH FLOW</p><h3>Outstanding balances</h3><div className="privacy-line"><span>Members with pending payments</span><b data-testid="report-outstanding">{money(summary?.outstanding)}</b></div><div className="privacy-line"><span>New members this month</span><b>{summary?.new_members_this_month ?? "—"}</b></div></article>
  </div>;
}

function Notifications({ items, refresh }) {
  const retry = async (id) => { await api.post(`/notifications/${id}/retry`); refresh(); };
  return <div className="page-content">
    <div className="panel table-panel"><div className="table-caption"><div><p className="eyebrow">DELIVERY LOG</p><h2>Notification centre <span>{items.length}</span></h2></div><div className="provider-banner"><MessageSquare size={15} /> WhatsApp provider disabled</div></div>
      <div className="notification-list">{items.length ? items.map((n) => <div data-testid={`notification-${n.id}`} className="notification-item" key={n.id}>
        <div className="notification-icon"><MessageSquare size={17} /></div>
        <div><strong>{n.type?.replaceAll("_", " ")}</strong><span>Member {n.member_id} · attempts: {n.attempts || 0}</span></div>
        <div className="notification-status">{n.status}</div>
        <small>{dateLabel(n.created_at)}</small>
        <button data-testid={`retry-${n.id}-button`} className="ghost-button" onClick={() => retry(n.id)}><RefreshCw size={13} /> Retry</button>
      </div>) : <Empty text="Notification records will appear here." />}</div>
    </div>
  </div>;
}

function AuditLog() {
  const [items, setItems] = useState([]);
  useEffect(() => { api.get("/audit").then((r) => setItems(r.data)); }, []);
  return <div className="page-content"><div className="panel table-panel"><div className="table-caption"><div><p className="eyebrow">TRACE</p><h2>Audit log <span>{items.length}</span></h2></div></div>
    <div className="notification-list">{items.length ? items.map((a) => <div key={a.id} data-testid={`audit-${a.id}`} className="notification-item">
      <div className="notification-icon"><ShieldCheck size={17} /></div>
      <div><strong>{a.action}</strong><span>{a.entity_type} · {a.entity_id}</span></div>
      <div className="notification-status">{a.actor_role || "SYSTEM"}</div>
      <small>{dateLabel(a.created_at)}</small>
    </div>) : <Empty text="No audit records yet." />}</div>
  </div></div>;
}

function SettingsPage() {
  const [settings, setSettings] = useState(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { api.get("/settings").then((r) => setSettings(r.data)); }, []);
  if (!settings) return <div className="page-content"><Empty text="Loading gym settings…" /></div>;
  const save = async (e) => {
    e.preventDefault();
    await api.put("/settings", { ...settings, expiry_reminder_days: Number(settings.expiry_reminder_days), grace_period_days: Number(settings.grace_period_days), retention_days: Number(settings.retention_days) });
    setSaved(true); setTimeout(() => setSaved(false), 2500);
  };
  return <div className="page-content"><form className="settings-form panel" onSubmit={save}>
    <div className="table-caption"><div><p className="eyebrow">OPERATING RULES</p><h2>Gym settings</h2></div><button data-testid="save-settings-button" className="primary-button">{saved ? "Saved ✓" : "Save changes"}</button></div>
    <div className="form-grid">
      <label>Gym name<input data-testid="settings-gym-name-input" value={settings.gym_name || ""} onChange={(e) => setSettings({ ...settings, gym_name: e.target.value })} /></label>
      <label>Gym phone<input data-testid="settings-gym-phone-input" value={settings.gym_phone || ""} onChange={(e) => setSettings({ ...settings, gym_phone: e.target.value })} /></label>
      <label>Gym address<input data-testid="settings-gym-address-input" value={settings.gym_address || ""} onChange={(e) => setSettings({ ...settings, gym_address: e.target.value })} /></label>
      <label>Timezone<input data-testid="settings-timezone-input" value={settings.timezone || "Asia/Kolkata"} onChange={(e) => setSettings({ ...settings, timezone: e.target.value })} /></label>
      <label>Expiry reminder days<input data-testid="settings-reminder-input" type="number" value={settings.expiry_reminder_days} onChange={(e) => setSettings({ ...settings, expiry_reminder_days: e.target.value })} /></label>
      <label>Grace period days<input data-testid="settings-grace-input" type="number" value={settings.grace_period_days} onChange={(e) => setSettings({ ...settings, grace_period_days: e.target.value })} /></label>
      <label>Retention days<input data-testid="settings-retention-input" type="number" value={settings.retention_days} onChange={(e) => setSettings({ ...settings, retention_days: e.target.value })} /></label>
    </div>
    <div className="settings-section">
      <p className="eyebrow">INTEGRATIONS</p>
      <div className="integration-row"><div className="integration-symbol whatsapp"><MessageSquare size={19} /></div><div><strong>WhatsApp Cloud API</strong><span>Provider abstraction ready · awaiting Meta credentials</span></div><span className="integration-state">Disabled</span></div>
      <div className="integration-row"><div className="integration-symbol storage"><Activity size={19} /></div><div><strong>Member photo storage</strong><span>Upload interface ready · awaiting object storage credentials</span></div><span className="integration-state">Disabled</span></div>
      <div className="integration-row"><div className="integration-symbol whatsapp"><ShieldCheck size={19} /></div><div><strong>Automated lifecycle</strong><span>APScheduler running daily at 00:15 Asia/Kolkata · notification retries every 15 minutes</span></div><span className="integration-state" style={{ color: "var(--green)" }}>Live</span></div>
    </div>
  </form></div>;
}

function App() {
  const [user, setUser] = useState(null);
  const [page, setPage] = useState("overview");
  const [collapsed, setCollapsed] = useState(false);
  const [data, setData] = useState(null);
  const [plans, setPlans] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [memberMode, setMemberMode] = useState(false);
  const [memberAuthed, setMemberAuthed] = useState(false);
  const [running, setRunning] = useState(false);
  const refresh = async () => {
    try { const [d, p, n] = await Promise.all([api.get("/dashboard"), api.get("/plans"), api.get("/notifications")]);
      setData(d.data); setPlans(p.data); setNotifications(n.data);
    } catch (err) { if (err.response?.status === 401) setUser(null); }
  };
  useEffect(() => { if (user) refresh(); }, [user]);
  const runJobs = async () => { setRunning(true); try { await api.post("/jobs/run"); await refresh(); } finally { setRunning(false); } };
  const pendingNotifs = useMemo(() => notifications.filter((n) => !["SENT", "FAILED_MAX_ATTEMPTS"].includes(n.status)).length, [notifications]);

  if (memberMode) {
    return memberAuthed
      ? <MemberPortal onExit={() => { setMemberAuthed(false); setMemberMode(false); }} />
      : <MemberLogin onMemberLogin={() => setMemberAuthed(true)} onBack={() => setMemberMode(false)} />;
  }
  if (!user) return <Login onLogin={setUser} onMember={() => setMemberMode(true)} />;
  const content = {
    overview: <Overview data={data} setPage={setPage} />,
    members: <Members members={data?.members || []} plans={plans} refresh={refresh} />,
    plans: <Plans plans={plans} refresh={refresh} />,
    payments: <Payments />,
    reports: <Reports data={data} />,
    notifications: <Notifications items={notifications} refresh={refresh} />,
    audit: <AuditLog />,
    settings: <SettingsPage />,
  }[page];
  return <div className="app-shell">
    <Sidebar page={page} setPage={setPage} collapsed={collapsed} setCollapsed={setCollapsed} notificationCount={pendingNotifs} onLogout={async () => { await api.post("/auth/logout"); setUser(null); }} />
    <main className="main-shell"><Topbar page={page} onMember={() => setMemberMode(true)} onRunJobs={runJobs} running={running} />{content}</main>
  </div>;
}

export default App;
