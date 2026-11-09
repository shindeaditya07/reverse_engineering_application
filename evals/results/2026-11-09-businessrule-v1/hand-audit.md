# Hand audit of businessrule-v1 (qwen2.5-coder:7b, recorded 2026-11-09)

Read by one reader (Claude, the author of the agent) against the cited code. It is not an
independent review: the human review queue is the real check. The key score only matches lines;
this file checks whether each sentence is true.

17 Inferred claims, 1 Unknown (a non-UTF-8 file, stated). Of the 17: **16 true, 1 false.**

**The false one**, `br:services/orders_service.js:30:3`: "Total is calculated by subtracting bulk
discounts, **adding** loyalty discount, tax, and shipping costs." The code subtracts the loyalty
discount (`- loyalty`). It reads as plausible, cited correctly, and passed the verifier. A
reviewer who skims would accept it. This is the failure the human gate exists for.

**True but not business rules** (mechanics, 3 claims): order insert, stock update, receipt/queue
description from one 27-line function, `placeOrder`. One long function produced 6 of the 17
claims (2 more were cut by the 6-per-span cap). Reviewer time goes to these.

**True and useful** (13): loyalty table, December 3% surcharge, 1 to 50 order lines, allowed
statuses, name 1 to 80, name over 60 rejected, order not found 404, closed 409, bulk discount,
free shipping threshold, ship next day from 14:00, plus two vaguer ones (subtotal from items;
payment retried without the 3 attempts or delays).

**V-10 demoted 3 claims, and all 3 are true** (December surcharge, free shipping, ship-by
14:00). The sentence uses words ("December", "next day", "free shipping") the code spells
differently (`getMonth() === 11`, `setDate(+1)`, `0 : 599`). So V-10 over-demotes correct
paraphrases, matching the earlier verifier-eval finding (5 of 7). Still undecided by Aditya.

**Missed** (model said "no rules" or the finder had no span): T05-F1 (`isOrderOpen` inverted),
T17-F1 (tax, no span), T23-F1 (payment retry timings), T33-F2 (`formatMoney`).

**Not found by the key but real**: the December surcharge, allowed statuses, free shipping and
the 5.99 flat rate are true rules the answer key does not list. Key precision stays a floor.
