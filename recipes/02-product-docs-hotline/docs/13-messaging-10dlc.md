# Sending SMS and 10DLC registration

You can send SMS and MMS from any SignalWire number that supports messaging, with the REST API, the SDKs or a SWML `send_sms` action.

## 10DLC in the United States

US carriers require application-to-person traffic from ordinary 10-digit long code numbers (10DLC) to be registered. Registration has three parts:

1. A brand: the business that sends the messages.
2. A campaign: what the messages are for, with sample messages and how people opt in.
3. Number assignment: each sending number is added to an approved campaign.

Messages from a number that is not assigned to an approved campaign may be blocked or filtered by carriers. Do the registration in the Dashboard under Messaging Campaigns. Approval can take some time, so start early.

## Opt-out

Honor opt-out keywords such as STOP. Do not send marketing messages to people who have not agreed to receive them.

Toll-free numbers have their own verification process, which is separate from 10DLC.
