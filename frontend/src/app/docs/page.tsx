import type { Metadata } from "next";
import Link from "next/link";
import { LegalLayout, legalH2Style, legalPStyle } from "@/components/legal/LegalLayout";

export const metadata: Metadata = {
  title: "Documentation",
  description:
    "How Clew connects to your AWS logs and how alerts, blocking, and billing work. The reference guide.",
};

const h3Style: React.CSSProperties = {
  fontSize: "15px",
  fontWeight: 700,
  marginTop: "24px",
  marginBottom: "10px",
};

const codeStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "12.5px",
  padding: "1px 5px",
  border: "1px solid var(--color-border)",
  background: "var(--color-surface)",
};

const preStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "12px",
  lineHeight: 1.6,
  border: "1px solid var(--color-border)",
  background: "var(--color-surface)",
  padding: "14px 16px",
  overflowX: "auto",
  whiteSpace: "pre",
  margin: "0 0 16px",
};

const tableWrapStyle: React.CSSProperties = {
  border: "1px solid var(--color-border)",
  marginBottom: "16px",
  overflowX: "auto",
};

const tableStyle: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: "13px",
};

const thStyle: React.CSSProperties = {
  padding: "8px 14px",
  textAlign: "left",
  fontSize: "11px",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  color: "var(--color-text-muted)",
  borderBottom: "1px solid var(--color-border)",
  fontWeight: 500,
  whiteSpace: "nowrap",
};

const tdStyle: React.CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--color-border)",
  verticalAlign: "top",
};

const linkStyle: React.CSSProperties = { color: "var(--color-text)" };

export default function DocsPage() {
  return (
    <LegalLayout title="Documentation" lastUpdated="October 1, 2026">
      <p style={legalPStyle}>
        Most people never need this page. The dashboard has a guided
        onboarding flow that walks you through setup in a few clicks. These
        docs are the reference version, for people who want the detail.
        <br />
        <Link href="/dashboard" style={linkStyle}>
          Open guided onboarding in your dashboard →
        </Link>
      </p>

      <h2 style={legalH2Style} id="quick-start">1. Quick start</h2>
      <p style={legalPStyle}>
        Register at <code style={codeStyle}>/register</code> with an email,
        password, and company name, then verify your email with the
        one-time code we send you. Every self-serve account starts
        immediately on the permanently free Starter plan, no card and no
        trial clock.
      </p>
      <p style={legalPStyle}>
        In Settings, connect your S3 bucket: bucket name, optional prefix,
        log format (API Gateway or ALB), and AWS region, then grant Clew
        read access to that bucket (see the next section). Once the
        connection test passes, Clew queues your first scan right away and
        checks for new logs every 15 minutes after that.
      </p>
      <p style={legalPStyle}>
        You can upgrade, downgrade, or add blocking integrations at any time
        from{" "}
        <Link href="/dashboard/settings#billing" style={linkStyle}>
          Settings → Plan &amp; Billing
        </Link>
        .
      </p>

      <h2 style={legalH2Style} id="connecting-your-log-source">
        2. Connecting your log source
      </h2>
      <p style={legalPStyle}>
        Clew reads your logs by assuming an IAM role inside your own AWS
        account, not by holding a long-lived access key. Your organisation
        gets its own External ID, shown read-only on{" "}
        <Link href="/dashboard/settings#s3" style={linkStyle}>
          Settings → AWS Access
        </Link>
        , which generates both policies below with your External ID and
        Clew&apos;s AWS account ID already filled in.
      </p>

      <h3 style={h3Style}>Cross-account IAM role</h3>
      <p style={legalPStyle}>1. Create an IAM role in your AWS account with this trust policy:</p>
      <pre style={preStyle}>{`{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::<CLEW_AWS_ACCOUNT_ID>:root" },
    "Action": "sts:AssumeRole",
    "Condition": { "StringEquals": { "sts:ExternalId": "<YOUR_EXTERNAL_ID>" } }
  }]
}`}</pre>
      <p style={legalPStyle}>
        2. Attach this permissions policy to the same role. Add the{" "}
        <code style={codeStyle}>wafv2</code> statement only if you want
        blocking, manual or automatic:
      </p>
      <pre style={preStyle}>{`{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": ["arn:aws:s3:::YOUR-BUCKET-NAME", "arn:aws:s3:::YOUR-BUCKET-NAME/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["wafv2:GetIPSet", "wafv2:UpdateIPSet"],
      "Resource": "*"
    }
  ]
}`}</pre>
      <p style={legalPStyle}>
        3. Paste the role ARN back into Settings. The connection test runs
        immediately. If you add blocking later, tick the checkbox on that
        page and update this same role, you never need a second one.
      </p>

      <h3 style={h3Style}>Legacy: bucket policy, no role</h3>
      <p style={legalPStyle}>
        Older accounts may still grant access with a bucket policy naming
        Clew&apos;s shared IAM user as principal. This keeps working if you
        have not yet switched to a role, but the role above is recommended
        for every new connection. Contact{" "}
        <a href="mailto:support@clewsec.com" style={linkStyle}>support@clewsec.com</a>{" "}
        if you need the bucket policy JSON.
      </p>

      <h2 style={legalH2Style} id="enabling-aws-api-gateway-access-logs-to-s3">
        3. Enabling AWS API Gateway access logs to S3
      </h2>
      <p style={legalPStyle}>
        Select &quot;API Gateway (apigw)&quot; as the log format in
        Settings. Clew expects a single-line JSON object per request:
      </p>
      <pre style={preStyle}>{`{
  "requestTime": "...", "ip": "...", "method": "...", "path": "...",
  "status": 200, "responseLength": 512, "latencyMs": 45, "userAgent": "..."
}`}</pre>
      <p style={legalPStyle}>
        API Gateway delivers access logs to CloudWatch Logs, not directly to
        S3, so route that log group into your bucket (a subscription filter
        with a small Kinesis Firehose delivery stream, or a one-off export
        task for an initial backfill). On first connection Clew checks a
        sample of your logs against the format you picked and tells you on
        Settings if it does not match.
      </p>

      <h2 style={legalH2Style} id="enabling-aws-alb-access-logs-to-s3">
        4. Enabling AWS ALB access logs to S3
      </h2>
      <p style={legalPStyle}>
        Select &quot;Application Load Balancer (alb)&quot; as the log format
        in Settings. An Application Load Balancer can log directly to S3,
        no Firehose needed: in the load balancer&apos;s attributes, enable
        access logs and point them at your bucket and prefix. Clew parses
        AWS&apos;s standard ALB access log format as-is.
      </p>

      <h2 style={legalH2Style} id="how-scanning-works">
        5. How scanning works
      </h2>
      <p style={legalPStyle}>
        Clew checks for new logs every 15 minutes. On a brand-new connection
        it also looks back over your last 7 days of logs so you are not
        starting from zero. Clew also takes a focused second look at any
        single IP making an unusually high number of requests within one
        scan, so a concentrated attacker spread across a wide window is not
        missed. Your dashboard&apos;s &quot;last scanned&quot; time updates
        every cycle, even when nothing suspicious is found, so you can see
        Clew is actively working.
      </p>
      <p style={legalPStyle}>
        <strong>Documented limitation:</strong> catching a single
        concentrated attacker needs a meaningful number of requests from
        that IP within one 15-minute window. A large number of distinct,
        low-volume IPs, for example a botnet making one attempt each, can
        currently evade detection. Recognising that kind of spread-out
        pattern across many IPs is on the roadmap, not built yet.
      </p>

      <h2 style={legalH2Style} id="understanding-verdicts">
        6. Understanding verdicts
      </h2>
      <p style={legalPStyle}>
        Every detection gets a confidence score from 0 to 1, which maps to a
        severity band:
      </p>
      <div style={tableWrapStyle}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Confidence</th>
              <th style={thStyle}>Severity</th>
            </tr>
          </thead>
          <tbody>
            <tr><td style={tdStyle}>0.80 and above</td><td style={tdStyle}>Critical</td></tr>
            <tr><td style={tdStyle}>0.60 to 0.79</td><td style={tdStyle}>High</td></tr>
            <tr><td style={tdStyle}>0.40 to 0.59</td><td style={tdStyle}>Medium</td></tr>
            <tr><td style={tdStyle}>Below 0.40</td><td style={tdStyle}>Low</td></tr>
          </tbody>
        </table>
      </div>
      <p style={legalPStyle}>
        Each verdict&apos;s detail page shows a score from every detection
        agent, a short sample of the raw requests involved, and, on the
        right plan, a written explanation. Threat types include DoS Flood,
        DDoS, Brute Force, Credential Stuffing, Bot Activity, Scraping,
        Port Scan, Enumeration, Sequence Abuse, Web Attack, Geo Anomaly, and
        Unknown Abuse for anything else. An IP you block manually with no
        prior detection is labelled Manual Block.
      </p>
      <p style={legalPStyle}>
        The &quot;cost prevented&quot; figure on a verdict is an estimate,
        not a measured cost, scaled by confidence using the same
        assumptions published on the pricing calculator on the homepage.
      </p>

      <h2 style={legalH2Style} id="the-detection-agents">
        7. The detection agents
      </h2>
      <p style={legalPStyle}>
        Six agents each look for a different kind of abuse on every batch of
        traffic, plus one passive agent that recognises known bad IPs
        across your history but does not vote on its own. Clew combines all
        six scores into one verdict. Some older material rounds this up to
        &quot;seven agents&quot;, that is imprecise: six are active.
      </p>
      <div style={tableWrapStyle}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Agent</th>
              <th style={thStyle}>What it looks for</th>
            </tr>
          </thead>
          <tbody>
            <tr><td style={tdStyle}><code style={codeStyle}>VolumeAgent</code></td><td style={tdStyle}>DoS / traffic floods</td></tr>
            <tr><td style={tdStyle}><code style={codeStyle}>TemporalAgent</code></td><td style={tdStyle}>Bot-like timing, off-hours activity</td></tr>
            <tr><td style={tdStyle}><code style={codeStyle}>AuthAgent</code></td><td style={tdStyle}>Brute force, credential stuffing</td></tr>
            <tr><td style={tdStyle}><code style={codeStyle}>PayloadAgent</code></td><td style={tdStyle}>SQLi, XSS, path traversal</td></tr>
            <tr><td style={tdStyle}><code style={codeStyle}>SequenceAgent</code></td><td style={tdStyle}>Endpoint enumeration / scanning</td></tr>
            <tr><td style={tdStyle}><code style={codeStyle}>GeoIPAgent</code></td><td style={tdStyle}>Geographic anomalies</td></tr>
            <tr><td style={tdStyle}><code style={codeStyle}>KnowledgeAgent</code></td><td style={tdStyle}>Known bad IPs, passive, casts no vote</td></tr>
          </tbody>
        </table>
      </div>

      <h2 style={legalH2Style} id="threat-explanations">
        8. Threat explanations
      </h2>
      <p style={legalPStyle}>
        Growth and above see a written, plain-English explanation of why a
        verdict was flagged on its detail page, generated from the IP
        address and aggregated request metrics only, never raw log content
        or request bodies. If that is ever unavailable, Clew falls back to
        an automatically generated description so the field is never empty.
        Starter and Basic see an upgrade prompt in its place.
      </p>

      <h2 style={legalH2Style} id="alerts">
        9. Alerts
      </h2>
      <p style={legalPStyle}>
        Set an alert email and a severity threshold, all threats or high and
        critical only, in{" "}
        <Link href="/dashboard/settings#alerts" style={linkStyle}>
          Settings → Alerts
        </Link>
        . Every delivery, sent or failed, is logged on the{" "}
        <Link href="/dashboard/alerts" style={linkStyle}>Alerts</Link> page,
        with a button to send yourself a test alert. Free Starter accounts
        do not receive email alerts, that starts at Basic.
      </p>

      <h2 style={legalH2Style} id="blocking-ips">
        10. Blocking IPs
      </h2>
      <p style={legalPStyle}>
        Manual blocking, a button on a verdict or a form to block an IP
        directly, is available from the Basic plan up. Automatic blocking,
        where Clew blocks the moment a high or critical threat is detected
        with no click required, is available from Growth up. Both push to
        AWS WAF and Cloudflare, whichever you configure in{" "}
        <Link href="/dashboard/settings#waf" style={linkStyle}>
          Settings → WAF Configuration
        </Link>{" "}
        and{" "}
        <Link href="/dashboard/settings#cloudflare" style={linkStyle}>
          Cloudflare Configuration
        </Link>
        . Configure either one, both, or neither, if neither is set up Clew
        never blocks anything, even on a plan that supports it.
      </p>
      <p style={legalPStyle}>
        Before your first block, your organisation accepts the Blocking
        Subscription Agreement once, automatically, the first time you
        check out on any paid plan.
      </p>
      <p style={legalPStyle}>
        Unblocking is never tier-gated. Even after a downgrade, you can
        always remove a block you already placed.
      </p>

      <h2 style={legalH2Style} id="team-and-roles">
        11. Team and roles
      </h2>
      <p style={legalPStyle}>Every organisation has three roles:</p>
      <div style={tableWrapStyle}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Action</th>
              <th style={thStyle}>Owner</th>
              <th style={thStyle}>Admin</th>
              <th style={thStyle}>Viewer</th>
            </tr>
          </thead>
          <tbody>
            <tr><td style={tdStyle}>View dashboard, verdicts, and IPs</td><td style={tdStyle}>Yes</td><td style={tdStyle}>Yes</td><td style={tdStyle}>Yes</td></tr>
            <tr><td style={tdStyle}>Configure S3, WAF, Cloudflare, alerts</td><td style={tdStyle}>Yes</td><td style={tdStyle}>Yes</td><td style={tdStyle}>No</td></tr>
            <tr><td style={tdStyle}>Block or unblock an IP</td><td style={tdStyle}>Yes</td><td style={tdStyle}>Yes</td><td style={tdStyle}>No</td></tr>
            <tr><td style={tdStyle}>Invite a team member</td><td style={tdStyle}>Yes</td><td style={tdStyle}>Viewer role only</td><td style={tdStyle}>No</td></tr>
            <tr><td style={tdStyle}>Change or remove a member</td><td style={tdStyle}>Yes</td><td style={tdStyle}>No</td><td style={tdStyle}>No</td></tr>
            <tr><td style={tdStyle}>View or manage billing</td><td style={tdStyle}>Yes</td><td style={tdStyle}>No</td><td style={tdStyle}>No</td></tr>
          </tbody>
        </table>
      </div>
      <p style={legalPStyle}>
        Invites to an email outside your organisation&apos;s own domain are
        capped at the viewer role. Manage your team from{" "}
        <Link href="/dashboard/settings#team" style={linkStyle}>
          Settings → Team Members
        </Link>
        .
      </p>

      <h2 style={legalH2Style} id="plans-limits-and-billing">
        12. Plans, limits, and billing
      </h2>
      <div style={tableWrapStyle}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Plan</th>
              <th style={thStyle}>Monthly call volume</th>
              <th style={thStyle}>History retention</th>
            </tr>
          </thead>
          <tbody>
            <tr><td style={tdStyle}>Starter (free)</td><td style={tdStyle}>2,000,000</td><td style={tdStyle}>7 days</td></tr>
            <tr><td style={tdStyle}>Basic</td><td style={tdStyle}>10,000,000</td><td style={tdStyle}>30 days</td></tr>
            <tr><td style={tdStyle}>Growth</td><td style={tdStyle}>50,000,000</td><td style={tdStyle}>90 days</td></tr>
            <tr><td style={tdStyle}>Pro</td><td style={tdStyle}>200,000,000</td><td style={tdStyle}>365 days</td></tr>
            <tr><td style={tdStyle}>Enterprise</td><td style={tdStyle}>No fixed cap</td><td style={tdStyle}>Unlimited</td></tr>
          </tbody>
        </table>
      </div>
      <p style={legalPStyle}>
        Going over your cap sends a warning email at 80% and again at 100%,
        Clew never stops scanning for being over a soft limit. Upgrading
        gives you access immediately; moving between two paid plans on or
        before the 15th charges only the price difference right away, after
        the 15th nothing is charged until your new plan&apos;s first invoice
        on the 1st. Downgrading keeps your current plan until the end of
        the billing cycle you&apos;ve already paid for.
      </p>
      <p style={legalPStyle}>
        A full refund is available within 72 hours of your very first
        payment, self-serve, one time. Today, self-serve payment is INR
        only through Razorpay, other currencies are invoiced manually.
      </p>

      <h2 style={legalH2Style} id="security-and-data-handling">
        13. Security and data handling
      </h2>
      <p style={legalPStyle}>
        Clew&apos;s access to your logs is read-only unless you separately
        opt in to blocking, which adds a narrowly scoped WAF permission to
        the same role. Clew stores parsed log metadata, the verdicts it
        produces, a short raw sample per detection, and IP reputation
        history, not your full raw log stream, all subject to your
        plan&apos;s retention window above.
      </p>
      <p style={legalPStyle}>
        Stored credentials and multi-factor secrets are encrypted at rest,
        passwords are hashed, never stored in plain text.
      </p>
      <p style={legalPStyle}>
        Request account deletion any time from Settings. Login is blocked
        immediately, and your data is permanently deleted within 30 days.
        See the{" "}
        <Link href="/legal/privacy" style={linkStyle}>Privacy Policy</Link>{" "}
        for the full list of subprocessors.
      </p>

      <h2 style={legalH2Style} id="faq">
        14. FAQ
      </h2>

      <h3 style={h3Style}>Is there a free plan?</h3>
      <p style={legalPStyle}>
        Yes, every self-serve signup starts on the permanently free Starter
        plan, no card, no trial, no expiry.
      </p>

      <h3 style={h3Style}>Which log formats are supported?</h3>
      <p style={legalPStyle}>AWS API Gateway and AWS Application Load Balancer access logs.</p>

      <h3 style={h3Style}>Do you store my raw logs?</h3>
      <p style={legalPStyle}>
        No, only parsed metadata, detections, and a short sample per
        detected verdict.
      </p>

      <h3 style={h3Style}>Can I use Clew without blocking?</h3>
      <p style={legalPStyle}>
        Yes, leave your WAF and Cloudflare fields empty and Clew will never
        take a blocking action, even on a plan that supports it.
      </p>

      <h3 style={h3Style}>What happens if I downgrade?</h3>
      <p style={legalPStyle}>
        Your current plan stays active until the end of the billing cycle
        you&apos;ve already paid for. You can always unblock an IP you
        previously blocked, at any tier.
      </p>

      <h3 style={h3Style}>What if I remove Clew&apos;s access on my side?</h3>
      <p style={legalPStyle}>
        Your next scan fails with an access error shown on your dashboard,
        nothing is deleted on Clew&apos;s side until you separately request
        account deletion.
      </p>
    </LegalLayout>
  );
}
