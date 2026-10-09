# mail-merge-online
Easy online alternative to mail merge for bulk email outreach (with schedule sending, previews, etc.) with support for web Outlook and Gmail.

## Start

Open **Start Mac.command** or **Start Windows.bat**, or run `python3 launch.py`. The launcher installs required dependencies when needed, then opens the app.

## Choose your mailbox

Select **Outlook web** or **Gmail web**. Enter the sending email address. Outlook uses your organization's HTTPS webmail address; Gmail uses `https://mail.google.com/mail/u/0/#inbox`. Custom-domain Google Workspace Gmail accounts are supported.

The app remembers the website and sending address separately for each service. Choose **Chromium** for the bundled browser, or **Google Chrome** if Chrome is installed on your computer. Sign in normally, including MFA. Google may restrict sign-in from automated browsers; the app does not bypass that restriction.

## Set up the website once per account

1. Click **Website setup**. Sign in, return to the inbox, and choose OK when ready.
2. Select **Compose / New mail**, then **Use selection** in the small browser panel.
3. Follow the panel to map the To and CC typing boxes, their highlighted recipient rows, Subject, Body, and Send. Selecting Send during setup does **not** send an email.
4. If Gmail collapses its recipient rows, also select the summary line that expands them when prompted.
5. Close or discard the empty compose form and return to the inbox when setup finishes.

The browser stays open between actions, including cancellations and errors. You can switch to other tabs or sections. Before a new action, the app prompts you to return to the correct account's inbox and close existing compose forms. If several mailbox tabs match, choose the intended tab in the app; other tabs can stay open. Closing a browser window is allowed—the app opens it again on the next action. Exiting the app closes the browsers it manages.

## Prepare your batch

1. Choose an `.xlsx`, `.csv`, or `.tsv` spreadsheet with headers and one recipient per row. Select the Email column and optional CC column.
2. Add shared recipients under **CC on every email**. Use plain addresses, separated by commas or semicolons.
3. Write the subject and plain-text body. Use placeholders such as `{{first_name}}` or `{{company}}`, matching spreadsheet column names. Include your signature; the app replaces the editable body.
4. Click **Preview** and select rows to review their rendered messages. **Export preview** saves a local CSV.
5. Use **Open first draft** to verify the actual website fields without sending. The browser and draft stay open after the check. Discard the test draft before sending the batch.

## Send now

Click **Send batch**, return to the inbox when prompted, and review the first actual email in the browser—including the sending account. Approve the batch in the app. The app verifies To, CC, Subject, and Body before each Send action, with your configured delay between messages.

**Stop** stops between messages after recording any current Send result. **Send history** shows what was submitted. Rerunning an unchanged batch skips submitted recipients. For an uncertain result, check Gmail **Sent** or Outlook **Sent Items** before resolving it in Send history. Editing the recipients, content, mailbox, or URL creates a different batch.

## Schedule a batch

Click **Schedule batch…**, enter a date (`YYYY-MM-DD`), 24-hour time (`HH:MM`), and timezone, then choose **Prepare scheduled batch**. The default timezone is **America/Chicago**. Sign in and approve the first draft now; the app waits until the selected time and then starts the batch, using the usual delay between messages.

**Scheduling runs on a local timer. Keep the app, browser, and computer open, awake, and connected until the batch finishes.** It does not queue messages in Gmail's online Scheduled folder. Stop cancels the timer. Restarting the app requires reviewing and scheduling again; it never automatically resumes a timer. Submitted-message history remains available.

Invalid or past times are rejected. Ambiguous or nonexistent daylight-saving times require a different time or UTC. If the computer wakes more than two minutes late, the task pauses instead of sending unexpectedly late.

## What runs where?

| Feature | Where it runs / is stored |
| --- | --- |
| Spreadsheet reading, personalization, validation, and preview | Locally on your computer |
| Template/settings, field mappings, and send history | Local `.mailmerge_state` folder beside the app |
| Saved browser sign-in | Local browser profile inside `.mailmerge_state`; passwords are entered on the mail website |
| Scheduled start and message delay | Local app timer; the computer must remain awake |
| Browser automation and recipient/content checks | Locally, controlling the visible webmail page |
| Draft autosaving, sending, delivery, provider limits, and bounces | Gmail or your Outlook/mail provider |

Protect `.mailmerge_state` as you would a signed-in browser. “Submitted” means the website accepted the Send action and the composer closed; it is not a delivery receipt. Check Sent / Sent Items and delivery reports if needed.
