#!/bin/bash
# ---------------------------------------------------------------------------
# env_check.bash -- show the FamilySearch settings Gramps will see
# ---------------------------------------------------------------------------
# Lists every GRAMPS_FS_* environment variable the FamilySearch code in
# gramps/gen/fs and gramps/gui/fs reads, with the value it will use. Secrets
# (the foundation access code and app keys) are never printed: only whether
# they are set and their length.
#
# Run it from the same shell you start Gramps from:
#   ./featuredocs/devnotes/familysearch/env_check.bash
#
# A variable that is not set falls back to what is shown in brackets: a Gramps
# preference (Edit > Preferences > Integrations) or a built-in default.
# FamilySearch must also be switched on there with "Enable FamilySearch
# integration"; that setting has no environment variable, so it isn't checked.
# See featuredocs/README_gwizard_familysearch.md for what each one does.
# ---------------------------------------------------------------------------

problems=0

is_on() {
    case "${1,,}" in
        1 | true | yes | on) return 0 ;;
        *) return 1 ;;
    esac
}

# show NAME DEFAULT -- plain value
show() {
    local name="$1" default="$2"
    local value="${!name}"
    if [[ -n "$value" ]]; then
        printf '  %-34s = %s\n' "$name" "$value"
    else
        printf '  %-34s   (not set; %s)\n' "$name" "$default"
    fi
}

# show_secret NAME DEFAULT -- never prints the value
show_secret() {
    local name="$1" default="$2"
    local value="${!name}"
    if [[ -n "$value" ]]; then
        printf '  %-34s = <set, %d characters>\n' "$name" "${#value}"
    else
        printf '  %-34s   (not set; %s)\n' "$name" "$default"
    fi
}

echo "Sign-in"
show GRAMPS_FS_AUTH_PROVIDER "Auth provider preference, default foundation"
show GRAMPS_FS_ENABLE_DIRECT "off: direct is turned into foundation"
show GRAMPS_FS_ENV "Server preference, default beta"
show GRAMPS_FS_AUTH_METHOD "auto"

echo
echo "Foundation middleware (auth provider foundation)"
show GRAMPS_FS_FOUNDATION_BASE_URL "Middleware base URL preference"
show_secret GRAMPS_FS_FOUNDATION_ACCESS_CODE "Middleware access code preference"

echo
echo "Your own FamilySearch app (auth provider direct)"
show_secret GRAMPS_FS_BETA_APP_KEY "App key preference"
show_secret GRAMPS_FS_PROD_APP_KEY "App key preference"
show GRAMPS_FS_BETA_REDIRECT "Redirect URL preference, default loopback"
show GRAMPS_FS_PROD_REDIRECT "Redirect URL preference, default loopback"
show GRAMPS_FS_OAUTH_SCOPE "profile email qualifies_for_affiliate_account country"

echo
echo "Older direct sign-in variables (see the README before using these)"
show_secret GRAMPS_FS_APP_KEY "only used when the App key preference is empty"
show GRAMPS_FS_REDIRECT "only used when the Redirect URL preference is empty"
show GRAMPS_FS_SERVER "0 = beta; only picks the site GRAMPS_FS_APP_KEY is for"

echo
echo "Timeouts (seconds)"
show GRAMPS_FS_LISTENER_TIMEOUT "300"
show GRAMPS_FS_API_TIMEOUT "30"

echo
echo "Troubleshooting"
show GRAMPS_FS_DEBUG "off"
show GRAMPS_FS_SHOW_STATUS "off"
show GRAMPS_FS_SHOW_TOOLS "on"

# ---- What Gramps will do with these -----------------------------------------
# Only the environment is checked here; a value set in Gramps preferences
# instead also counts, so "missing" means "missing unless it's in preferences".
provider="${GRAMPS_FS_AUTH_PROVIDER,,}"
provider="${provider:-foundation (unless preferences say otherwise)}"
if [[ "$provider" == "direct" ]] && ! is_on "$GRAMPS_FS_ENABLE_DIRECT"; then
    provider="foundation (direct asked for, but GRAMPS_FS_ENABLE_DIRECT is off)"
fi

echo
echo "Auth provider Gramps will use: $provider"
if [[ "$provider" == direct ]]; then
    # Gramps won't start a session without the App key preference or
    # GRAMPS_FS_APP_KEY, even when a BETA_/PROD_ key is set.
    if [[ -z "$GRAMPS_FS_APP_KEY" ]]; then
        echo "  missing: an app key (needed unless App key is set in preferences)"
        problems=1
    fi
else
    for name in GRAMPS_FS_FOUNDATION_BASE_URL GRAMPS_FS_FOUNDATION_ACCESS_CODE; do
        if [[ -z "${!name}" ]]; then
            echo "  missing: $name (needed unless set in preferences)"
            problems=1
        fi
    done
fi

if [[ -n "$GRAMPS_FS_ENV" ]] && [[ ! "${GRAMPS_FS_ENV,,}" =~ ^(beta|prod)$ ]]; then
    echo "  GRAMPS_FS_ENV must be beta or prod; '$GRAMPS_FS_ENV' is ignored"
    problems=1
fi
if [[ -n "$GRAMPS_FS_AUTH_METHOD" ]] &&
    [[ ! "${GRAMPS_FS_AUTH_METHOD,,}" =~ ^(auto|webkit|loopback|manual)$ ]]; then
    echo "  GRAMPS_FS_AUTH_METHOD must be auto, webkit, loopback or manual"
    problems=1
fi

# Older names this script used to print. Gramps never reads them, so a
# value in one of them has no effect.
for name in GRAMPS_FS_AUTH_TOKEN GRAMPS_FS_AUTH_USER GRAMPS_FS_AUTH_PASS \
    GRAMPS_FS_AUTH_URL GRAMPS_FS_FOUNDATION_API_URL \
    GRAMPS_FS_FOUNDATION_API_VERSION; do
    if [[ -n "${!name}" ]]; then
        echo "  $name is set but Gramps does not use it"
    fi
done

if [[ $problems -eq 0 ]]; then
    echo "  No problems found in the environment."
fi
exit $problems
