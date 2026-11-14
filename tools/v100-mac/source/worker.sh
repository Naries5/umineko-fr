#!/bin/bash
set -u
export LC_ALL=UTF-8

ACTION="${1:-status}"
GAME_ROOT_ARG="${2:-}"
MANIFEST_URL="https://raw.githubusercontent.com/Naries5/umineko-fr/main/update/manifest.json"
SUPPORT="$HOME/Library/Application Support/LeSanglotDesGoelands/PatcherMac"
JXA="$SUPPORT/manifest_tools.js"
STATE="$SUPPORT/state.tsv"
RESULT="$SUPPORT/result.tsv"
SETTINGS="$SUPPORT/game_root.txt"
LOG_DIR="$HOME/Library/Logs"
LOG_FILE="$LOG_DIR/LeSanglotDesGoelands-Patcher-Mac.log"

/bin/mkdir -p "$SUPPORT" "$LOG_DIR"
/usr/bin/touch "$LOG_FILE"

log() { /bin/echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }
sanitize() { /usr/bin/printf '%s' "$1" | /usr/bin/tr '\t\r\n' '   '; }
state() {
    local pct="$1" title="$2" detail="$3"
    local tmp="$STATE.tmp.$$"
    /usr/bin/printf '%s\t%s\t%s\n' "$pct" "$(sanitize "$title")" "$(sanitize "$detail")" > "$tmp"
    /bin/mv -f "$tmp" "$STATE"
}
result() {
    /usr/bin/printf '%b\n' "$*" > "$RESULT"
}
fail() {
    log "ERREUR: $1"
    state 100 "Erreur" "$1"
    result "ERROR\t$(sanitize "$1")"
    exit 1
}

find_game_root() {
    local selected="$1"
    selected="${selected%/}"
    if [ -f "$selected/0.u" ] && [ -d "$selected/bmp" ]; then
        /usr/bin/printf '%s\n' "$selected"; return 0
    fi
    local candidate parent
    while IFS= read -r candidate; do
        [ -n "$candidate" ] || continue
        parent=$(/usr/bin/dirname "$candidate")
        if [ -d "$parent/bmp" ]; then
            /usr/bin/printf '%s\n' "$parent"; return 0
        fi
    done < <(/usr/bin/find "$selected" -type f -name "0.u" -print 2>/dev/null | /usr/bin/head -n 20)
    return 1
}

detect_07th_mod() {
    local root="$1" json="$1/installedVersionData.json"
    if [ -f "$json" ]; then
        if /usr/bin/grep -Eqi 'Umineko Question \(Ch\. 1-4\)/full' "$json" && \
           /usr/bin/grep -Eqi '"id"[[:space:]]*:[[:space:]]*"script"' "$json" && \
           /usr/bin/grep -Eqi '"id"[[:space:]]*:[[:space:]]*"exe"' "$json"; then
            return 0
        fi
    fi
    if [ -f "$root/fonts/oldface0.ttf" ] && { [ -d "$root/big" ] || [ -f "$root/arc4.nsa" ]; }; then
        return 0
    fi
    return 1
}

# Locate Steam installs in default locations, additional Steam libraries and mounted volumes.
# Only known game-directory candidates are checked, never an unrestricted disk-wide scan.
resolve_game_root() {
    local candidate="" root="" library="" vdf="" match="" base=""
    if [ -n "$GAME_ROOT_ARG" ]; then
        GAME_ROOT=$(find_game_root "$GAME_ROOT_ARG" 2>/dev/null || true)
        [ -n "$GAME_ROOT" ] && return 0
    fi
    if [ -f "$SETTINGS" ]; then
        candidate=$(/bin/cat "$SETTINGS" 2>/dev/null || true)
        GAME_ROOT=$(find_game_root "$candidate" 2>/dev/null || true)
        [ -n "$GAME_ROOT" ] && return 0
    fi
    for base in "$HOME/Library/Application Support/Steam" "$HOME/.steam/steam" "$HOME/.local/share/Steam"; do
        for candidate in "$base/steamapps/common/Umineko" "$base/steamapps/common/Umineko - Question Arcs" "$base/steamapps/common/Umineko When They Cry - Question Arcs" "$base/steamapps/common/Umineko When They Cry - Question Arcs (07th-Mod)"; do
            if [ -f "$candidate/0.u" ] && [ -d "$candidate/bmp" ]; then GAME_ROOT="$candidate"; return 0; fi
        done
        vdf="$base/steamapps/libraryfolders.vdf"
        if [ -f "$vdf" ]; then
            while IFS= read -r library; do
                [ -n "$library" ] || continue
                for candidate in "$library/steamapps/common/Umineko" "$library/steamapps/common/Umineko - Question Arcs" "$library/steamapps/common/Umineko When They Cry - Question Arcs"; do
                    if [ -f "$candidate/0.u" ] && [ -d "$candidate/bmp" ]; then GAME_ROOT="$candidate"; return 0; fi
                done
            done < <(/usr/bin/sed -nE 's/^[[:space:]]*"path"[[:space:]]*"(.*)"[[:space:]]*$/\1/p' "$vdf" | /usr/bin/sed 's#\\#/#g')
        fi
    done
    for base in /Volumes/*; do
        [ -d "$base" ] || continue
        for candidate in "$base/SteamLibrary/steamapps/common/Umineko" "$base/SteamLibrary/steamapps/common/Umineko When They Cry - Question Arcs" "$base/steamapps/common/Umineko"; do
            if [ -f "$candidate/0.u" ] && [ -d "$candidate/bmp" ]; then GAME_ROOT="$candidate"; return 0; fi
        done
    done
    return 1
}

sha256_file() { /usr/bin/shasum -a 256 "$1" | /usr/bin/awk '{print $1}'; }

normalize_stage_paths() {
    /usr/bin/find "$STAGE" -depth -print0 2>/dev/null | while IFS= read -r -d '' p; do
        [ "$p" = "$STAGE" ] && continue
        rel="${p#$STAGE/}"
        case "$rel" in
            *\\*)
                normalized=$(/usr/bin/printf '%s' "$rel" | /usr/bin/tr '\\' '/')
                dest="$STAGE/$normalized"
                if [ -d "$p" ]; then
                    /bin/mkdir -p "$dest"
                    /bin/rmdir "$p" 2>/dev/null || true
                else
                    /bin/mkdir -p "$(/usr/bin/dirname "$dest")"
                    /bin/mv -f "$p" "$dest"
                fi
                ;;
        esac
    done
}

rollback_backup() {
    local backup="$1" manifest="$1/backup_manifest.tsv" existed rel dst src
    [ -f "$manifest" ] || return 0
    while IFS=$'\t' read -r existed rel; do
        [ -n "$rel" ] || continue
        dst="$GAME_ROOT/$rel"
        if [ "$existed" = "1" ]; then
            src="$backup/files/$rel"
            /bin/mkdir -p "$(/usr/bin/dirname "$dst")"
            /bin/cp -p "$src" "$dst" 2>/dev/null || true
        else
            /bin/rm -f "$dst" 2>/dev/null || true
        fi
    done < "$manifest"
}

uninstall_patch() {
    local base="$GAME_ROOT/.umineko_fr_backup_mac"
    [ -d "$base" ] || fail "Aucun backup du patch FR n'a été trouvé. Désinstallation annulée pour ne pas toucher à 07th-Mod."

    local backup_count=0 b manifest existed rel dst src total_all=0 done_all=0

    # Compte les backups et les opérations.
    while IFS= read -r b; do
        [ -d "$b" ] || continue
        manifest="$b/backup_manifest.tsv"
        [ -f "$manifest" ] || continue
        backup_count=$((backup_count+1))
        c=$(/usr/bin/grep -cve '^[[:space:]]*$' "$manifest" || true)
        total_all=$((total_all+c))
    done < <(/bin/ls -1dr "$base"/20* 2>/dev/null || true)

    [ "$backup_count" -gt 0 ] || fail "Aucun backup exploitable du patch FR n'a été trouvé."
    denom="$total_all"; [ "$denom" -gt 0 ] || denom=1

    state 5 "Désinstallation" "$backup_count backup(s) à restaurer..."

    # Du plus récent au plus ancien : cela remonte jusqu'à l'état d'avant
    # la toute première installation du patch FR.
    while IFS= read -r b; do
        [ -d "$b" ] || continue
        manifest="$b/backup_manifest.tsv"
        [ -f "$manifest" ] || continue

        while IFS=$'\t' read -r existed rel; do
            [ -n "$rel" ] || continue
            dst="$GAME_ROOT/$rel"

            if [ "$existed" = "1" ]; then
                src="$b/files/$rel"
                [ -e "$src" ] || fail "Backup incomplet : $rel est introuvable dans $b"
                /bin/mkdir -p "$(/usr/bin/dirname "$dst")"
                /bin/cp -p "$src" "$dst" || fail "Impossible de restaurer $rel"
            else
                /bin/rm -f "$dst" 2>/dev/null || true
            fi

            done_all=$((done_all+1))
            if [ $((done_all % 50)) -eq 0 ] || [ "$done_all" -eq "$total_all" ]; then
                state $((5 + done_all * 90 / denom)) "Désinstallation" "$done_all / $total_all fichiers"
            fi
        done < "$manifest"
    done < <(/bin/ls -1dr "$base"/20* 2>/dev/null || true)

    # Par sécurité, le marqueur FR disparaît après désinstallation.
    /bin/rm -f "$GAME_ROOT/umineko_fr_version.txt" 2>/dev/null || true

    # Les backups appartiennent au patch FR ; une désinstallation complète les retire.
    /bin/rm -rf "$base" 2>/dev/null || true

    state 100 "Désinstallation terminée" "Le patch FR a été retiré. 07th-Mod est conservé."
    result "OK\tuninstalled"
    log "Patch FR désinstallé."
    exit 0
}

prepare_manifest() {
    TMP_BASE="${TMPDIR:-/tmp}"
    TMP_DIR=$(/usr/bin/mktemp -d "$TMP_BASE/umineko-fr-mac.XXXXXX") || fail "Impossible de créer le dossier temporaire."
    trap '/bin/rm -rf "$TMP_DIR"' EXIT
    MANIFEST="$TMP_DIR/manifest.json"
    FILES_TSV="$TMP_DIR/files.tsv"
    PACKAGES_TSV="$TMP_DIR/packages.tsv"
    NEEDED_PACKAGES="$TMP_DIR/needed_packages.txt"
    CHANGED_FILES="$TMP_DIR/changed_files.tsv"
    STAGE="$TMP_DIR/stage"
    PKG_STAGE="$TMP_DIR/package_stage"
    DOWNLOADS="$TMP_DIR/downloads"
    : > "$NEEDED_PACKAGES"
    : > "$CHANGED_FILES"
    /bin/mkdir -p "$STAGE" "$DOWNLOADS" "$PKG_STAGE"
    state 2 "Connexion à GitHub" "Téléchargement du manifest..."
    # Automatic Steam launches must not be blocked for a minute by a slow network.
    local connect_timeout=20 max_time=60
    if [ "$ACTION" = "update" ]; then connect_timeout=5; max_time=15; fi
    /usr/bin/curl -fsSL --connect-timeout "$connect_timeout" --max-time "$max_time" \
        -H "Cache-Control: no-cache" \
        -A "Le-Sanglot-des-Goelands-Mac-Patcher" \
        "$MANIFEST_URL" -o "$MANIFEST" || fail "Impossible de télécharger le manifest GitHub."
    REMOTE_VERSION=$(/usr/bin/osascript -l JavaScript "$JXA" version "$MANIFEST" 2>/dev/null) || fail "Manifest invalide."
    REMOTE_NOTES=""
    if [ "$ACTION" = "status" ]; then
        REMOTE_NOTES=$(/usr/bin/osascript -l JavaScript "$JXA" notes "$MANIFEST" 2>/dev/null || true)
    fi
    [ -n "$REMOTE_VERSION" ] || fail "Version distante absente du manifest."
}

load_manifest_entries() {
    /usr/bin/osascript -l JavaScript "$JXA" files "$MANIFEST" > "$FILES_TSV" || fail "Impossible de lire la liste des fichiers."
    /usr/bin/osascript -l JavaScript "$JXA" packages "$MANIFEST" > "$PACKAGES_TSV" || fail "Impossible de lire la liste des packages."
}

scan_files() {
    TOTAL=$(/usr/bin/grep -cve '^[[:space:]]*$' "$FILES_TSV" || true)
    CHANGED=0
    CHANGED_BYTES=0
    local done=0 rel expected size package_id dst actual denom
    denom="$TOTAL"; [ "$denom" -gt 0 ] || denom=1
    while IFS=$'\t' read -r rel expected size package_id; do
        [ -n "$rel" ] || continue
        done=$((done+1))
        dst="$GAME_ROOT/$rel"
        actual=""
        if [ -f "$dst" ]; then actual=$(sha256_file "$dst" 2>/dev/null || true); fi
        if [ "$actual" != "$expected" ]; then
            CHANGED=$((CHANGED+1))
            case "$size" in ''|*[!0-9]*) size=0 ;; esac
            CHANGED_BYTES=$((CHANGED_BYTES+size))
            /usr/bin/printf '%s\t%s\n' "$rel" "$package_id" >> "$CHANGED_FILES"
            if ! /usr/bin/grep -Fxq "$package_id" "$NEEDED_PACKAGES" 2>/dev/null; then
                /usr/bin/printf '%s\n' "$package_id" >> "$NEEDED_PACKAGES"
            fi
        fi
        if [ $((done % 50)) -eq 0 ] || [ "$done" -eq "$TOTAL" ]; then
            state $((5 + done * 30 / denom)) "Vérification des fichiers" "$done / $TOTAL fichiers"
        fi
    done < "$FILES_TSV"
}

/bin/rm -f "$STATE" "$RESULT" 2>/dev/null || true
log "=== Action $ACTION ==="

if ! resolve_game_root; then
    if [ "$ACTION" = "status" ]; then
        /usr/bin/printf 'NEED_GAME\n'
        exit 0
    fi
    fail "Installation Umineko introuvable."
fi

if ! detect_07th_mod "$GAME_ROOT"; then
    if [ "$ACTION" = "status" ]; then
        /usr/bin/printf 'NO_07TH\t%s\n' "$GAME_ROOT"
        exit 0
    fi
    fail "07th-Mod complet non détecté."
fi

/usr/bin/printf '%s\n' "$GAME_ROOT" > "$SETTINGS"
LOCAL_VERSION="0"
if [ -f "$GAME_ROOT/umineko_fr_version.txt" ]; then
    LOCAL_VERSION=$(/usr/bin/tr -d '\r\n' < "$GAME_ROOT/umineko_fr_version.txt")
    [ -n "$LOCAL_VERSION" ] || LOCAL_VERSION="0"
fi

if [ "$ACTION" = "uninstall" ]; then uninstall_patch; fi

prepare_manifest

if [ "$ACTION" = "status" ]; then
    /usr/bin/printf 'OK\t%s\t%s\t%s\t%s\n' "$GAME_ROOT" "$LOCAL_VERSION" "$REMOTE_VERSION" "$(sanitize "$REMOTE_NOTES")"
    exit 0
fi

# Steam launch fast path: the local version marker is written ONLY after a
# successful, SHA-256-verified installation. If nothing new is advertised,
# avoid hashing all 4047 files again. Manual Verify/Repair still scans all.
if [ "$ACTION" = "update" ] && [ "$LOCAL_VERSION" = "$REMOTE_VERSION" ] && [ "$LOCAL_VERSION" != "0" ] && \
   [ -s "$GAME_ROOT/0.u" ] && [ -d "$GAME_ROOT/bmp" ]; then
    log "Steam: patch $REMOTE_VERSION already installed; full hash scan skipped."
    state 100 "Déjà à jour" "Version $REMOTE_VERSION : lancement rapide."
    result "OK\tup_to_date\t$REMOTE_VERSION\tfast"
    exit 0
fi

load_manifest_entries
scan_files

if [ "$ACTION" = "verify" ]; then
    state 100 "Vérification terminée" "$CHANGED fichier(s) différent(s) sur $TOTAL."
    result "OK\tverified\t$LOCAL_VERSION\t$REMOTE_VERSION\t$TOTAL\t$CHANGED"
    exit 0
fi

if [ "$CHANGED" -eq 0 ]; then
    /usr/bin/printf '%s\n' "$REMOTE_VERSION" > "$GAME_ROOT/umineko_fr_version.txt"
    state 100 "Déjà à jour" "Tous les fichiers correspondent à la version $REMOTE_VERSION."
    result "OK\tup_to_date\t$REMOTE_VERSION\t$TOTAL"
    exit 0
fi

PACKAGE_COUNT=$(/usr/bin/grep -cve '^[[:space:]]*$' "$NEEDED_PACKAGES" || true)
PKG_DONE=0
state 36 "Téléchargement" "$PACKAGE_COUNT package(s) nécessaire(s)"

while IFS= read -r package_id; do
    [ -n "$package_id" ] || continue
    row=$(/usr/bin/awk -F '\t' -v id="$package_id" '$1 == id {print; exit}' "$PACKAGES_TSV")
    [ -n "$row" ] || fail "Package $package_id absent du manifest."
    IFS=$'\t' read -r pid url expected_zip size_zip <<EOF
$row
EOF
    zip="$DOWNLOADS/$pid.zip"
    state $((36 + PKG_DONE * 24 / (PACKAGE_COUNT > 0 ? PACKAGE_COUNT : 1))) "Téléchargement" "$pid ($((PKG_DONE+1)) / $PACKAGE_COUNT)"
    /usr/bin/curl -fsSL --connect-timeout 20 \
        -A "Le-Sanglot-des-Goelands-Mac-Patcher/0.6" \
        "$url" -o "$zip" || fail "Échec du téléchargement de $pid."
    actual_zip=$(sha256_file "$zip" 2>/dev/null || true)
    [ "$actual_zip" = "$expected_zip" ] || fail "SHA-256 incorrect pour $pid."
    isolated="$PKG_STAGE/$pid"
    /bin/mkdir -p "$isolated"
    /usr/bin/ditto -x -k "$zip" "$isolated" || fail "Impossible d'extraire $pid."
    STAGE="$isolated"
    normalize_stage_paths
    PKG_DONE=$((PKG_DONE+1))
done < "$NEEDED_PACKAGES"

# Preflight: verify every required file from its owning package, BEFORE backing up
# or writing any file to the installed game. This prevents archive order conflicts.
state 60 "Contrôle des archives" "Vérification des fichiers extraits"
PRECHECK_FAIL=0
while IFS=$'\t' read -r rel package_id; do
    [ -n "$rel" ] || continue
    case "$rel" in /*|../*|*/../*|*'/..'|*'\'*|*'//'*) fail "Chemin dangereux dans le manifest : $rel";; esac
    case "$package_id" in ''|*'/'*|*'\'*|*'..'*) fail "Identifiant de paquet invalide : $package_id";; esac
    expected=$(/usr/bin/awk -F '\t' -v p="$rel" '$1 == p {print $2; exit}' "$FILES_TSV")
    src="$PKG_STAGE/$package_id/$rel"
    actual=$(sha256_file "$src" 2>/dev/null || true)
    if [ -z "$expected" ] || [ "$actual" != "$expected" ]; then
        PRECHECK_FAIL=$((PRECHECK_FAIL+1))
        log "PRECHECK FAIL: $rel | paquet=$package_id | attendu=$expected | obtenu=$actual"
    fi
done < "$CHANGED_FILES"
[ "$PRECHECK_FAIL" -eq 0 ] || fail "$PRECHECK_FAIL fichier(s) incorrect(s) avant installation ; aucun fichier du jeu modifié. Consulte le journal."

STAMP=$(/bin/date '+%Y%m%d-%H%M%S')
BACKUP="$GAME_ROOT/.umineko_fr_backup_mac/$STAMP"
BACKUP_FILES="$BACKUP/files"
BACKUP_MANIFEST="$BACKUP/backup_manifest.tsv"
/bin/mkdir -p "$BACKUP_FILES"
: > "$BACKUP_MANIFEST"

CHANGED_TOTAL=$(/usr/bin/grep -cve '^[[:space:]]*$' "$CHANGED_FILES" || true)

# La version locale fait partie du backup à partir de la GUI 0.5.
if [ -f "$GAME_ROOT/umineko_fr_version.txt" ]; then
    /bin/mkdir -p "$BACKUP_FILES"
    /bin/cp -p "$GAME_ROOT/umineko_fr_version.txt" "$BACKUP_FILES/umineko_fr_version.txt" || fail "Impossible de sauvegarder la version locale."
    /usr/bin/printf '1\tumineko_fr_version.txt\n' >> "$BACKUP_MANIFEST"
else
    /usr/bin/printf '0\tumineko_fr_version.txt\n' >> "$BACKUP_MANIFEST"
fi

DONE=0
DENOM="$CHANGED_TOTAL"; [ "$DENOM" -gt 0 ] || DENOM=1
while IFS=$'\t' read -r rel package_id; do
    [ -n "$rel" ] || continue
    case "$rel" in /*|../*|*/../*|*'\'*|*'//'*) fail "Chemin de suppression dangereux : $rel";; esac
    dst="$GAME_ROOT/$rel"
    if [ -e "$dst" ]; then
        backup_dst="$BACKUP_FILES/$rel"
        /bin/mkdir -p "$(/usr/bin/dirname "$backup_dst")"
        /bin/cp -p "$dst" "$backup_dst" || { rollback_backup "$BACKUP"; fail "Impossible de sauvegarder $rel."; }
        /usr/bin/printf '1\t%s\n' "$rel" >> "$BACKUP_MANIFEST"
    else
        /usr/bin/printf '0\t%s\n' "$rel" >> "$BACKUP_MANIFEST"
    fi
    DONE=$((DONE+1))
    if [ $((DONE % 50)) -eq 0 ] || [ "$DONE" -eq "$CHANGED_TOTAL" ]; then
        state $((61 + DONE * 9 / DENOM)) "Sauvegarde" "$DONE / $CHANGED_TOTAL fichiers"
    fi
done < "$CHANGED_FILES"

DONE=0
while IFS=$'\t' read -r rel package_id; do
    [ -n "$rel" ] || continue
    src="$PKG_STAGE/$package_id/$rel"; dst="$GAME_ROOT/$rel"
    [ -f "$src" ] || { rollback_backup "$BACKUP"; fail "Fichier $rel absent des packages extraits."; }
    /bin/mkdir -p "$(/usr/bin/dirname "$dst")"
    /bin/cp -p "$src" "$dst" || { rollback_backup "$BACKUP"; fail "Échec de copie de $rel. Le backup a été restauré."; }
    DONE=$((DONE+1))
    if [ $((DONE % 50)) -eq 0 ] || [ "$DONE" -eq "$CHANGED_TOTAL" ]; then
        state $((71 + DONE * 17 / DENOM)) "Installation" "$DONE / $CHANGED_TOTAL fichiers"
    fi
done < "$CHANGED_FILES"

DELETE_PATHS="$TMP_DIR/delete_paths.txt"
/usr/bin/osascript -l JavaScript "$JXA" deletePaths "$MANIFEST" > "$DELETE_PATHS" 2>/dev/null || true
while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    case "$rel" in /*|../*|*/../*|*'\'*|*'//'*) fail "Chemin de suppression dangereux : $rel";; esac
    dst="$GAME_ROOT/$rel"
    if [ -e "$dst" ]; then
        backup_dst="$BACKUP_FILES/$rel"
        /bin/mkdir -p "$(/usr/bin/dirname "$backup_dst")"
        /bin/cp -p "$dst" "$backup_dst" 2>/dev/null || true
        /usr/bin/printf '1\t%s\n' "$rel" >> "$BACKUP_MANIFEST"
        /bin/rm -rf "$dst" || { rollback_backup "$BACKUP"; fail "Impossible de supprimer $rel."; }
    fi
done < "$DELETE_PATHS"

VERIFY_FAIL=0; DONE=0
while IFS=$'\t' read -r rel package_id; do
    [ -n "$rel" ] || continue
    expected=$(/usr/bin/awk -F '\t' -v p="$rel" '$1 == p {print $2; exit}' "$FILES_TSV")
    actual=$(sha256_file "$GAME_ROOT/$rel" 2>/dev/null || true)
    if [ -z "$expected" ] || [ "$actual" != "$expected" ]; then
        VERIFY_FAIL=$((VERIFY_FAIL+1))
        log "POSTCHECK FAIL: $rel | attendu=$expected | obtenu=$actual"
    fi
    DONE=$((DONE+1))
    if [ $((DONE % 50)) -eq 0 ] || [ "$DONE" -eq "$CHANGED_TOTAL" ]; then
        state $((89 + DONE * 10 / DENOM)) "Contrôle final" "$DONE / $CHANGED_TOTAL fichiers"
    fi
done < "$CHANGED_FILES"

if [ "$VERIFY_FAIL" -ne 0 ]; then
    rollback_backup "$BACKUP"
    fail "$VERIFY_FAIL fichier(s) ne correspondent pas au manifest après copie. Le backup a été restauré."
fi

BADPATHS="$BACKUP/prototype_0.3_bad_paths"
while IFS= read -r -d '' bad; do
    name=$(/usr/bin/basename "$bad")
    case "$name" in
        bmp\\*|en\\*|textbox\\*|fr_bg\\*)
            /bin/mkdir -p "$BADPATHS"
            /bin/mv "$bad" "$BADPATHS/" 2>/dev/null || true
            ;;
    esac
done < <(/usr/bin/find "$GAME_ROOT" -maxdepth 1 -mindepth 1 -name '*\\*' -print0 2>/dev/null)

/usr/bin/printf '%s\n' "$REMOTE_VERSION" > "$GAME_ROOT/umineko_fr_version.txt"
state 100 "Installation terminée" "Version $REMOTE_VERSION installée avec succès."
result "OK\tinstalled\t$REMOTE_VERSION\t$CHANGED_TOTAL\t$BACKUP"
log "Patch $REMOTE_VERSION installé. $CHANGED_TOTAL fichiers modifiés."
exit 0
