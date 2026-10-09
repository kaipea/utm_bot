# Unpacked UTM bot

Makes consistently tagged Unpacked links inside one Telegram group, and logs each one to a Google Sheet.

**In the group:** `/utm https://<your-substack>/p/some-post` (or reply `/utm` to a message that has the link) → pick a source → pick a medium → copy the link.

- Sources: telegram, whatsapp, linkedin, facebook, instagram, x, reddit, email, or **Other…** (typed, then cleaned up and marked `custom` in the sheet)
- Mediums: social, messaging, email, referral, outreach
- Campaign: post slug + the date the link was made (SGT), e.g. `budget-2027-explained-20261009`
- Only the person who ran `/utm` can press their buttons. Unfinished requests expire after 15 minutes.
- To change the button lists, edit `SOURCES` / `MEDIUMS` at the top of `utm.py`.

## Setup (about 20 minutes)

1. **Bot:** In @BotFather, `/newbot`, then copy the token. Leave privacy mode **on**: the bot still sees its commands and replies to its own messages, and nothing else.
2. **Group ID:** Deploy once without `ALLOWED_GROUP_ID`, add the bot to the group, and send `/chatid`. Put that number (it starts with `-100`) into `ALLOWED_GROUP_ID` and redeploy.
3. **Sheet:**
   - In Google Cloud, create a project, enable the **Google Sheets API**, create a **service account**, and download its JSON key.
   - Create a blank Sheet and share it (Editor) with the service account's `client_email`.
   - Copy the Sheet ID from its URL. The bot writes the header row itself.
4. **Railway:** Create a new service from this folder or repo and set the variables in `.env.example`. Paste the JSON key into `GOOGLE_SERVICE_ACCOUNT_JSON` as one line. The `Procfile` runs it as a worker; no web port is needed.
5. Set `ALLOWED_HOSTS` to your Substack domain. If you have a custom domain, add it too, comma-separated.

If the sheet ever fails, the link is still returned with a warning and the error goes to the Railway logs.

## Before you roll it out

Check that Substack actually records UTMs in the subscriber export. Subscribe a test email through a tagged link, then look at "Subscription source (free)" in the next export.
