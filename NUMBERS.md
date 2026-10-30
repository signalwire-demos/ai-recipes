# Demo number pool

Ten numbers bought on 2026-10-30 (wave 0) on the demo Space `briankwest.signalwire.com`, all
in area code 918 (Yale, OK rate center), all with voice, SMS, MMS and fax. Each number's
name on the Space is `ai-recipes <ROLE>`. The same `ROLE=+1...` lines are in
`~/workdir/demos/.env`, so recipes read them by role name. Numbers aren't secrets.

Builders: don't buy numbers and don't repoint them. The lead points numbers at
`briankwest.ngrok.io` during live calls (`scripts/live_slot.sh` + `scripts/smoke_call.py`).
In fixtures and READMEs, use the 555-01xx range, not these numbers.

| Role | Number | Used by | Notes |
|---|---|---|---|
| `TEST_INBOUND` | +19183951340 | Every recipe's live call (#1–#36 inbound) | `smoke_call.py` points its call handler at `PUBLIC_URL` with the recipe's basic auth |
| `TEST_CALLER` | +19183951341 | `smoke_call.py` caller leg; the "customer" phone for outbound recipes (#4, #14, #15 callback, #17, #29 dial-back) | Its handler is set per test to a scripted-caller SWML |
| `OUTBOUND_1` | +19183951448 | `FROM_NUMBER` for outbound dials: #4, #14, #15, #17, #29 | Caller ID on REST `calling.dial` |
| `OUTBOUND_2` | +19183951452 | `FROM_NUMBER` for `rpc_dial`/`connect` legs: #9 (adjuster), #15 (human), #19 (forward); #36 harness caller | Keeps the second leg's caller ID distinct from OUTBOUND_1 |
| `SMS_1` | +19183951694 | SMS sender: #19 (message to owner), #26 (supervisor alert), #27, #29 | Not yet on the 10DLC campaign; see below |
| `HUMAN_LEG` | +19183952006 | The human side: #9 adjuster, #15 support human, #19 office line | For unattended tests, point it at a simulated-human SWML (answer, speak, send DTMF 1). For a real person, set `ADJUSTER_NUMBER` etc. to a real phone in the recipe `.env` |
| `HUMAN_LEG_2` | +19183953488 | #19 on-call line; #23/#24 rep leg | Same simulated-human approach |
| `TENANT_1` | +19183953528 | #33 tenant: dental office | Dynamic config picks the tenant by called number |
| `TENANT_2` | +19183955034 | #33 tenant: HVAC company | |
| `TENANT_3` | +19183955056 | #33 tenant: law firm | |

## SMS (10DLC) status

- Brand `B7QKAPI` (state completed) has one campaign, **AI Agent Testing**
  (`CL7FMCJ`, id `6d8c87d6-0588-48b8-a8c6-b866146b54f2`), state **active**.
- On 2026-10-30 the campaign had **0 numbers assigned**. None of the pool numbers is on it yet.
- Before #19, #26 or #29 sends real SMS, assign `SMS_1` (and any other sender) to the
  campaign. With the SDK: `client.registry.campaigns.create_order(campaign_id, phone_numbers=["+19183951694"])`,
  then wait for the order to complete (`client.registry.orders.get(order_id)`). This is a lead
  or account-owner action, not a builder one.

## Purchase record

| Number | Phone number id | Bought (UTC) |
|---|---|---|
| +19183951340 | 26a75cc9-2097-480b-b72f-3554522314a9 | 2026-10-30T13:11:19Z |
| +19183951341 | c23df8f9-9aaa-4985-9dc9-7470ea038e2c | 2026-10-30T13:11:19Z |
| +19183951448 | 2223a327-092b-4ca9-ab13-66b735509535 | 2026-10-30T13:11:20Z |
| +19183951452 | cb6f88de-8a04-473a-afc9-d2ccd08f5eb2 | 2026-10-30T13:11:20Z |
| +19183951694 | b41ff164-c64c-42e7-9cda-298cc192fa71 | 2026-10-30T13:11:21Z |
| +19183952006 | df1c6a66-e403-42fb-a407-fa802fab7875 | 2026-10-30T13:11:21Z |
| +19183953488 | c473f58c-23ef-4f97-b1ed-0c2d8ca99b16 | 2026-10-30T13:11:22Z |
| +19183953528 | 49a845bf-0bab-4eeb-b95f-947a3ace9970 | 2026-10-30T13:11:22Z |
| +19183955034 | 2cc97a82-3583-4c42-bcc8-521faed712ca | 2026-10-30T13:11:22Z |
| +19183955056 | f0412ad9-89aa-42c0-abc1-56d12f54d303 | 2026-10-30T13:11:23Z |

Bought through `client.phone_numbers.search(areacode="918")` then
`client.phone_numbers.create(number=...)`. The project owned no numbers before this, so all
10 of the authorized 10 were used. No 405 fallback was needed. Don't buy more without the
account owner's approval.
