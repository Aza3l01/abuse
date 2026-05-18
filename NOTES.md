# Notes

## The "Twice the Money" Style Claim

"We'll save you twice what you pay us" is a classic ROI guarantee and it works when you can actually prove it. Some SaaS companies offer it as a formal money-back guarantee. The problem at your stage is you can't guarantee it because you don't control what abuse they're actually experiencing.

What you can say honestly and effectively instead:

"If after 30 days the dashboard isn't showing you at least 10x your monthly cost in prevented exposure, cancel and pay nothing."

10x sounds aggressive but API abuse at scale almost always justifies it because compute costs are real and fraud exposure is real. If a company is genuinely not seeing 10x ROI it probably means their abuse problem is small, which means they probably weren't the right customer anyway.

This framing does two things: it signals confidence in the product, and it pre-qualifies customers. A CTO who's worried about ROI at ₹4,999/month probably doesn't have a serious enough abuse problem to be your customer yet.

---

## The Sequencing You've Identified is Correct

Free monitoring first, blocking after commitment, is exactly right and here's the structural reason why:

Monitoring is read-only. You're just watching their logs. Zero risk to their production system. Any CTO can approve this in 5 minutes.

Blocking touches production. WAF rules, middleware, inline proxy all have the potential to cause a false positive that breaks a legitimate API call. That's a production incident risk. No CTO approves that from a vendor they've known for 10 days.

By the time they've seen 60-90 days of accurate detection with low false positives, the blocking conversation is easy. "You've seen us flag X requests, our false positive rate has been Y%, want us to start blocking automatically?" They already trust the detection, blocking is just the next logical step.

The trust has to be earned before you touch production. Your sequencing understands that intuitively.