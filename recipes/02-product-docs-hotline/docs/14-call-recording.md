# Recording calls

The `record_call` verb starts a recording in the background while the call continues. The `stop_record_call` verb stops it. Give the recording a `control_id` so you can stop the right one later.

Options include the format (for example `wav`, `mp3` or `mp4`), stereo recording with each side of the call on its own channel, and a status URL that receives an event when the recording is ready.

From an AI agent, a function can start or stop a recording by returning a record call or stop record call action. A common pattern is to stop the recording before collecting payment details, so card numbers are never recorded.

Recordings are stored in your Space and listed in the Dashboard. Tell callers when a call is recorded, and follow the consent laws that apply where you and your callers are.
