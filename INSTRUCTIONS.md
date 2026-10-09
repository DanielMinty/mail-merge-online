# Web Mail Merge — quick instructions

## Start and choose an account

On an Apple Silicon Mac, download **Web-Mail-Merge-macOS-arm64.zip** from the
repository root, unzip it, and open **Web Mail Merge.app**. It includes Python
and the app dependencies. The first browser action downloads Chromium if needed.
To run the source instead, use `python3 src/launch.py` from this project folder.
Select **Outlook web** or **Gmail web**, and enter your sending email address.
For Outlook, enter your organization's HTTPS webmail address. Gmail uses
`https://mail.google.com/mail/u/0/#inbox`, including Google Workspace accounts.
The app remembers the address and website separately for each service.

Choose **Chromium** (bundled) or **Google Chrome** (requires Chrome installed).
Sign in on the website normally, including MFA.

## Set up the website once per account

1. Click **Website setup**, sign in, return to the inbox, and choose OK.
2. Select **Compose / New mail**, then **Use selection** in the browser panel.
3. Follow the panel to map To, CC, their highlighted recipient rows, Subject,
   Body, and Send. Selecting Send during setup does **not** send a message.
4. If prompted, select Gmail's collapsed recipient summary line.
5. Discard the empty setup message, return to the inbox, and finish setup.

The browser stays open between steps and actions, including errors and
cancellations. Switch tabs or mailbox sections as needed. Before a new action,
the app prompts you to return to the correct account's inbox and close existing
compose forms. When several mailbox tabs match, choose one in the app; other
tabs can remain open. Closing the browser yourself is fine: the app reopens it
on the next action. Exiting the app closes its managed browsers.

## Prepare and send

1. Choose an `.xlsx`, `.csv`, or `.tsv` file with headers and one recipient per
   row. Select the Email column and optional CC column.
2. Use **CC on every email** for shared CC recipients, separated by commas or
   semicolons.
3. Write the subject and plain-text body. Use placeholders matching spreadsheet
   headers, such as `{{first_name}}`. Include your signature: the app replaces
   the website's editable body.
4. Click **Preview** and select rows to review complete messages.
   **Export preview** saves a local CSV.
5. Use **Open first draft** to check the actual website fields without sending.
   The draft and browser remain open. Discard this draft before a batch.
6. Click **Send batch**, follow the inbox prompt, review the first actual email
   and sending account, and approve in the app. It verifies recipients, subject,
   and body before each Send action.

**Stop** stops between messages after recording any current Send result.
**Send history** records submitted messages. Rerunning an unchanged batch skips
submitted recipients. For an uncertain result, check Gmail **Sent** or Outlook
**Sent Items** before resolving it in history. Changing recipients, content,
account, or URL creates a different batch.

## Schedule sending

Click **Schedule batch…**. Enter a date (`YYYY-MM-DD`), 24-hour time (`HH:MM`),
and timezone, then choose **Prepare scheduled batch**. The default timezone is
**UTC**. Choose your own timezone before scheduling. Review and approve the first draft now. At the chosen time,
the app starts the batch, using the configured delay between messages.

**Scheduling uses a local timer. Keep the app, browser, and computer open,
awake, and connected until sending finishes.** Messages are not queued in
Gmail's online Scheduled folder. Stop cancels the timer. After restarting the
app, review and schedule again; timers never resume automatically. Send history
is preserved.

Past or invalid times are rejected. Ambiguous or nonexistent daylight-saving
times require a different time or UTC. If the computer wakes more than two
minutes late, the task pauses instead of sending unexpectedly late.

## What runs locally?

| Feature | Where it runs or is stored |
| --- | --- |
| Spreadsheet reading, personalization, validation, and preview | Your computer |
| Settings, templates, field mappings, and send history | Mac app: `~/Library/Application Support/Web Mail Merge`; source checkout: local `.mailmerge_state` folder |
| Saved sign-in session | Local browser profile in the same data folder |
| Scheduled start and delay between messages | Local app timer; computer must stay awake |
| Browser automation and message checks | Your computer, controlling webmail |
| Draft autosaving, email sending, delivery, limits, and bounces | Gmail or your Outlook/mail provider |

Protect the local data folder as you would a signed-in browser. “Submitted” means
the Send action was accepted and the composer closed; it is not a delivery
receipt. Check Sent / Sent Items and delivery reports when needed.
