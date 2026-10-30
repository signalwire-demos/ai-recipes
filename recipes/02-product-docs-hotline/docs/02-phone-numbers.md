# Buying and configuring phone numbers

You can buy phone numbers in the Dashboard under Phone Numbers, or with the REST API. Search by area code or by the digits you want, then buy the number. Numbers can support voice, SMS, MMS and fax, depending on the number.

## Call handlers

Every number has a call handler that decides what happens when someone calls it. The common choices are:

- A SWML script stored in your Space. The script runs when a call arrives.
- A SWML webhook URL. SignalWire fetches SWML from your server for each call. This is how an Agents SDK app answers calls.
- A cXML (LaML) webhook or application, for code written against the cXML compatibility API.
- A relay context or topic, for apps that use the realtime Relay SDK.

To point a number at your own agent, open the number in the Dashboard, choose a SWML webhook as the call handler and paste your public URL. If the app uses basic authentication, put the user name and password in the URL: `https://user:pass@example.ngrok.app/`.

## Releasing numbers

A number you release goes back to the pool and may be bought by someone else. Release numbers only when you are sure you no longer need them.
