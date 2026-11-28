## Overview

GWizard FamilySearch Merge is a Gramps tool that searches FamilySearch for profiles and relatives of a person in your family tree and compares and merges the data side by side with the open Family Tree. It also adds FamilySearch as a record source for the **Multi-Archive Record Scan** and as a citation source for the **Multi-Archive Citation Scan**.

Before you can use it, Gramps has to be able to sign in to FamilySearch. The [Setup](#setup) section below explains how.

## Setup

### Turn on FamilySearch

FamilySearch is off in a new Gramps install. Choose **Edit** → **Preferences**, open the **Integrations** tab, and tick **Enable FamilySearch integration**. There is no environment variable for this. Until it is ticked, the FamilySearch tools can't sign in, whatever else is set.

### Choose how Gramps signs in

Gramps signs in to FamilySearch in one of two ways, called the *auth provider*:

- **Foundation middleware** (`foundation`, the default). Gramps signs in through a FamilySearch middleware service. You need the service's base URL and its access code. You don't need a FamilySearch app key of your own.
- **Direct FamilySearch** (`direct`). Gramps signs in straight to FamilySearch with your own FamilySearch developer app key. This choice only appears, and only works, when the environment variable `GRAMPS_FS_ENABLE_DIRECT` is on. When it is off, Gramps switches the auth provider back to `foundation`.

Most settings can be entered on the **Integrations** tab instead of as environment variables:

| Preference | Environment variable |
|---|---|
| **Server** (Beta / Live) | `GRAMPS_FS_ENV` |
| **Auth provider** | `GRAMPS_FS_AUTH_PROVIDER` |
| **Middleware base URL** | `GRAMPS_FS_FOUNDATION_BASE_URL` |
| **Middleware access code (issued secret)** | `GRAMPS_FS_FOUNDATION_ACCESS_CODE` |
| **App key (direct mode only)** | `GRAMPS_FS_BETA_APP_KEY` / `GRAMPS_FS_PROD_APP_KEY` |
| **Redirect URL (direct mode only)** | `GRAMPS_FS_BETA_REDIRECT` / `GRAMPS_FS_PROD_REDIRECT` |

When both are set, the environment variable wins.

### Environment variables

On/off variables are on when set to `1`, `true`, `yes` or `on`, in any case.

#### Choosing how to sign in

| Variable | Values | If not set | What it does |
|---|---|---|---|
| `GRAMPS_FS_AUTH_PROVIDER` | `foundation`, `direct` | **Auth provider** preference (default `foundation`) | How Gramps signs in (see above). |
| `GRAMPS_FS_ENABLE_DIRECT` | on/off | Off | Allows the `direct` auth provider and shows the app key and redirect boxes in preferences. Leave it off to use foundation. |
| `GRAMPS_FS_ENV` | `beta`, `prod` | **Server** preference (default Beta) | Which FamilySearch to use: the beta test site (`beta.familysearch.org`) or the real one (`www.familysearch.org`, shown as **Live** in preferences). |
| `GRAMPS_FS_AUTH_METHOD` | `auto`, `webkit`, `loopback`, `manual` | `auto` | How the sign-in page is shown. `webkit` opens an embedded login window. It isn't available on Windows, where Gramps uses `loopback` instead. `loopback` opens your web browser, and Gramps waits for FamilySearch to send the browser back to a small listener on your computer. `manual` prints the sign-in URL for you to open yourself. `auto` picks `webkit` when it can, and otherwise `loopback` (or `manual`, for direct sign-in with a redirect that isn't a `127.0.0.1` or `localhost` address). |

#### Foundation sign-in (needed when the auth provider is `foundation`)

| Variable | If not set | What it does |
|---|---|---|
| `GRAMPS_FS_FOUNDATION_BASE_URL` | **Middleware base URL** preference | Base URL of the FamilySearch middleware service. A trailing `/` is ignored. |
| `GRAMPS_FS_FOUNDATION_ACCESS_CODE` | **Middleware access code** preference | The access code issued for the middleware service. Keep it private. |

Both are required: with either missing, the FamilySearch tools can't sign in.

#### Direct sign-in (used when the auth provider is `direct`)

| Variable | If not set | What it does |
|---|---|---|
| `GRAMPS_FS_BETA_APP_KEY` | **App key** preference | Your FamilySearch app key (client ID) for the beta site. |
| `GRAMPS_FS_PROD_APP_KEY` | **App key** preference | Your FamilySearch app key for the real (prod) site. |
| `GRAMPS_FS_BETA_REDIRECT` | **Redirect URL** preference (default `http://127.0.0.1:57938/familysearch-auth`) | Redirect URL registered for your beta app key. |
| `GRAMPS_FS_PROD_REDIRECT` | **Redirect URL** preference (default `http://127.0.0.1:57938/familysearch-auth`) | Redirect URL registered for your prod app key. |
| `GRAMPS_FS_OAUTH_SCOPE` | `profile email qualifies_for_affiliate_account country` | The OAuth scope requested when signing in. |

For loopback sign-in, the redirect must be a `127.0.0.1` or `localhost` address. The listener uses the host, port and path from it.

An app key must also be in the **App key** preference or in `GRAMPS_FS_APP_KEY`, or Gramps won't start a FamilySearch session even when a `BETA_` / `PROD_` key is set. The easiest setup is to enter your app key in preferences.

Older variables that still work but are easy to get wrong:

| Variable | What it does |
|---|---|
| `GRAMPS_FS_APP_KEY` | App key, used only when the **App key** preference is empty, and only for the site `GRAMPS_FS_SERVER` names. Prefer the `BETA_` / `PROD_` variables. |
| `GRAMPS_FS_REDIRECT` | Redirect URL, used only when the **Redirect URL** preference is empty. That preference has a default, so in practice this variable is never used. Prefer the `BETA_` / `PROD_` variables. |
| `GRAMPS_FS_SERVER` | `0` for beta, `1` for prod. Only decides which site `GRAMPS_FS_APP_KEY` applies to. It doesn't choose the site: use `GRAMPS_FS_ENV` or the **Server** preference for that. |

#### Timeouts

| Variable | If not set | What it does |
|---|---|---|
| `GRAMPS_FS_LISTENER_TIMEOUT` | `300` | Seconds the loopback listener waits for you to finish signing in. |
| `GRAMPS_FS_API_TIMEOUT` | `30` | Seconds to wait for each FamilySearch request. |

#### Troubleshooting

| Variable | If not set | What it does |
|---|---|---|
| `GRAMPS_FS_DEBUG` | Off | Writes FamilySearch debug messages to the log and prints the sign-in URL. |
| `GRAMPS_FS_SHOW_STATUS` | Off | Shows the FamilySearch connection status window when a session starts. |
| `GRAMPS_FS_SHOW_TOOLS` | On | Set to `0`, `false`, `no` or `off` to stop the FamilySearch tools window from opening on its own. |

### Setting the variables

Gramps only sees variables that are set before it starts. After changing one, restart Gramps.

**Gramps started from a Windows shortcut or the Start menu.** Set the variables as Windows user (or system) environment variables, either in **Settings** → **System** → **About** → **Advanced system settings** → **Environment Variables**, or from a Command Prompt:

```bat
setx GRAMPS_FS_FOUNDATION_BASE_URL https://middleware.example.org
setx GRAMPS_FS_FOUNDATION_ACCESS_CODE your-access-code
setx GRAMPS_FS_ENV prod
```

`setx` only affects programs started afterwards, so open a new window (or sign out and back in) before starting Gramps.

**Gramps started from an MSYS2, Linux or macOS shell.** Export the variables in that shell, or add them to `~/.bashrc` (MSYS2 and Linux) or `~/.zshrc` (macOS):

```bash
export GRAMPS_FS_FOUNDATION_BASE_URL=https://middleware.example.org
export GRAMPS_FS_FOUNDATION_ACCESS_CODE=your-access-code
export GRAMPS_FS_ENV=prod
```

Replace the example URL and access code with the real ones. For direct sign-in, set `GRAMPS_FS_ENABLE_DIRECT=1` and `GRAMPS_FS_AUTH_PROVIDER=direct`, then enter your app key and redirect URL in preferences (or use the `BETA_` / `PROD_` variables) instead of the two foundation settings.

### Checking the setup

From the shell you start Gramps from, run:

```bash
./featuredocs/devnotes/familysearch/env_check.bash
```

It lists every variable above with the value Gramps will see, says which auth provider Gramps will use, and reports anything missing or invalid. It never prints the access code or app keys, only whether they are set. It can only see environment variables, so a setting that is only in preferences is reported as "missing unless set in preferences", and it can't tell whether **Enable FamilySearch integration** is ticked.

## Usage

[TODO: describe the GWizard FamilySearch Merge window, the FamilySearch search, the merge step, and the FamilySearch columns in the Multi-Archive Record Scan and Multi-Archive Citation Scan.]
