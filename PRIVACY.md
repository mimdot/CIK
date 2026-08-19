# Privacy

**Short version: Astra runs on your machine and keeps your data there.**

There is no Astra server. Nothing you type, search for or save is sent to us,
because there is no "us" to send it to.

## What Astra stores, and where

Everything lives in a single SQLite database on your own computer:

| Platform | Location |
|---|---|
| Linux | `~/.local/share/com.astra.app/astra.db` |
| macOS | `~/Library/Application Support/com.astra.app/` |
| Windows | `%APPDATA%\com.astra.app\` |

That file holds your email address, your research profile (field and
keywords), the positions and supervisors the engine found, and anything you
saved — including your notes and application status.

Alongside it, `api.log` records the backend's own startup and errors. It is
there so a failure can be diagnosed; it contains no search content.

Your email is also remembered in the app's local storage so you are not asked
for it on every launch. Signing out clears it.

Delete the folder above and every trace of your use of Astra is gone.

## What leaves your machine

Only the searches themselves. To find positions and supervisors, Astra fetches
public pages and APIs — academic job boards, EURAXESS, FindAPhD, NASA ADS,
OpenAlex, arXiv and the university department pages for your field.

Those requests contain your **search terms** (field keywords, country), because
that is what a search is. They do not contain your email, your profile, your
saved items or your notes.

If you configure a proxy, that traffic goes through it — including on
restricted networks, which is the case Astra was built for.

## What Astra does not do

- **No analytics, no telemetry, no crash reporting.** Nothing counts you.
- **No accounts on a server.** The account is a row in your local database.
- **No AI calls.** CV reading and the drafting assistant are switched off in
  this build (`CV_PARSING_ENABLED`, `ASSISTANT_ENABLED`). Nothing you write is
  sent to a model provider.
- **Nothing is sold or shared.** There is no third party to share it with.

## About the access code

The desktop app asks for an email and a shared access code. **This is not a
security measure**, and it does not protect your data. The code ships inside
the application and anyone can read it out of the binary. It exists so the
front door asks for something. Do not treat it as a lock.

Your email is not verified and is not sent anywhere. It exists to name the
local account that owns your profile and saved items.

## Removing your data

Quit Astra and delete the folder listed above. There is nothing held elsewhere,
so there is nothing to request deletion of.

If a future version ever does send something — and any such version would say
so here first, and ask before doing it — you can reach the author at
**mr.nasirzadeh@live.com** to have it removed.

## Changes

This document describes Astra 1.0.0. If data handling changes, this file
changes with it and the change is listed in [CHANGELOG.md](CHANGELOG.md).
