# Phonics Class (Django)

Classroom phonics blending game: kid profiles with PIN login, points + streaks,
weekly leaderboard with a cooperative class goal, and a teacher dashboard for
weekly word lists, point resets, and trouble-sound reports.

## Quick start (development)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser   # this is the teacher account
python manage.py seedwords         # optional starter word list
python manage.py runserver
```

- Kids: http://127.0.0.1:8000/ (pick name, enter PIN, play)
- Teacher dashboard: http://127.0.0.1:8000/teacher/
- Django admin: http://127.0.0.1:8000/admin/

## Weekly teacher routine

1. Open /teacher/ and log in.
2. "New week: deactivate all" then paste the new word list (one per line,
   optional `,level`). Or just toggle individual words on/off.
3. "Reset weekly points" (all-time totals and streaks are kept).

## Letter sounds

The game says each letter/digraph by playing `/sound/<grapheme>/` (e.g. `/sound/SH/`),
and each whole word via `/wordsound/<word>/`. Priority for a letter sound is:
(1) a teacher recording/upload, (2) a Google TTS file already cached on disk,
(3) Google TTS generated on the spot and then cached. A custom whole-word
recording overrides the browser's spoken word; otherwise it uses speech synthesis.

On the teacher dashboard, the **Letter sounds** card lists every supported sound
with **▶ Play**, **🎙 Record** (uses your microphone — needs HTTPS), and an
upload-file form. The **Words** card has the same ▶/🎙 controls per word.

### Recording sounds (recommended)

Recording your own voice is the most accurate and licence-free option. It needs
a microphone and HTTPS (see the deploy notes below).

Every recording (and uploaded/imported file) is automatically cleaned up in the
background: leading/trailing and gap silence is trimmed, steady background noise
is reduced, and the loudness is normalised, then it is saved as a mono MP3. This
uses a bundled ffmpeg binary (`imageio-ffmpeg`), so no system ffmpeg install is
needed. The cleanup thresholds live in `game/audio.py` and are tunable.

### Importing downloaded sounds

If you download sound files from a free source (see below), name each file after
its sound (`SH.mp3`, `CH.wav`, `A.mp3`, ...), drop them in a folder, then:

```bash
python manage.py importsounds /path/to/folder
```

### Finding free sound files

- Wikimedia Commons has free IPA pronunciation audio (e.g. search "IPA audio").
- Open-licensed phonics packs are available from sites like freesound.org
  (filter by Creative Commons 0) — be sure to check each file's licence.
- You can also use Google TTS (below) as a fallback for anything you haven't
  recorded yet.

### Google TTS fallback

To pre-build the Google sounds so kids get instant audio:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
python manage.py makevoices
```

- Create a Google Cloud service account, enable the **Cloud Text-to-Speech**
  API, and download its JSON key. Point `GOOGLE_APPLICATION_CREDENTIALS` at it
  (set it in the environment or the systemd unit).
- `GOOGLE_TTS_VOICE` optionally overrides the voice (default `en-US-Neural2-C`).
- A custom recording always wins over Google TTS.

## Production deploy (home server)

Set environment variables (e.g. in the systemd unit):

```
DJANGO_SECRET_KEY=<long random string>
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=phonics.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://phonics.example.com
```

Then:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn phonics_project.wsgi -b 127.0.0.1:8000 --workers 2
```

### systemd unit (`/etc/systemd/system/phonics.service`)

```ini
[Unit]
Description=Phonics Class (gunicorn)
After=network.target

[Service]
User=phonics
WorkingDirectory=/home/phonics/phonics-class
Environment=DJANGO_SECRET_KEY=CHANGE-ME
Environment=DJANGO_DEBUG=0
Environment=DJANGO_ALLOWED_HOSTS=phonics.example.com
Environment=DJANGO_CSRF_TRUSTED_ORIGINS=https://phonics.example.com
ExecStart=/home/phonics/phonics-class/venv/bin/gunicorn phonics_project.wsgi -b 127.0.0.1:8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```

`sudo systemctl enable --now phonics`

### HTTPS (required for the microphone / Sound Studio)

Browsers only allow mic access over HTTPS. Two good free options:

**Option A - Cloudflare Tunnel (no port forwarding, hides home IP):**

```bash
# install cloudflared, then:
cloudflared tunnel login
cloudflared tunnel create phonics
cloudflared tunnel route dns phonics phonics.example.com
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: phonics
credentials-file: /home/phonics/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: phonics.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

`sudo cloudflared service install` (installs its own systemd unit).

**Option B - DuckDNS + Caddy (port-forward 80/443 on the router):**

Caddyfile:

```
phonics.duckdns.org {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy fetches Let's Encrypt certs automatically.

### Backups

The whole database is one file. Daily cron:

```
0 2 * * * cp /home/phonics/phonics-class/db.sqlite3 /home/phonics/backups/db-$(date +\%F).sqlite3
```

## Notes

- Kid PINs are stored in plain text on purpose: they are kid-proofing, not
  security, and the teacher needs to read them back to kids who forget.
  The teacher account uses real hashed Django auth.
- No emails or personal data are collected for kids - just a nickname, icon
  and PIN.
