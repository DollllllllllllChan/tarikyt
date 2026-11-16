# Video Downloader GUI v2

Desktop Windows downloader berbasis Python, PySide6, dan `yt-dlp`.

Version: `v2.0.0`

## Quick Start

1. Jalankan `python main.py` dari folder `YouTube-Downloader-GUI-v2`.
2. Paste URL YouTube, TikTok, Instagram, X/Twitter, atau playlist di tab Download.
3. Klik `Test Link` untuk cek apakah link bisa dibaca dan apakah perlu cookies.
4. Pilih preset, kualitas, format, dan mode kualitas. Untuk gambar, pilih format `Image`.
5. Klik `Cek Resolusi`.
6. Klik `Download`.

State, settings, dan history v2 memakai file sendiri:

- `yt_downloader_v2_state.json`
- `yt_downloader_v2_settings.json`
- `yt_downloader_v2_history.jsonl`

## Fitur v2

- Nama aplikasi dan window: Video Downloader GUI v2.
- Versioning aplikasi: `v2.0.0`.
- Simple Mode / Power Mode.
- Preset profile.
- Status live speed dan ETA tanpa spam log.
- Status merge/post-processing untuk file besar.
- Queue context menu.
- History v2 dengan search, filter, dan action.
- Clean Temp Files.
- About dialog.
- Output EXE v2 terpisah dari v1.

## Perbedaan dari v1

v2 dibuat di folder terpisah dan tidak memakai file state/history/settings v1.

v1 tetap memakai:

- `yt_downloader_state.json`
- `yt_downloader_history.jsonl`
- `dist\YouTube Downloader.exe`

v2 memakai:

- `yt_downloader_v2_state.json`
- `yt_downloader_v2_history.jsonl`
- `yt_downloader_v2_settings.json`
- `dist\YouTube Downloader GUI v2.exe`

## Preset Profile

- `Custom`
- `Fast 720p`
- `Normal 1080p MP4`
- `High Quality 4K MKV`
- `Audio MP3`
- `Playlist Safe`

Jika setting diubah manual setelah memilih preset, preset otomatis menjadi `Custom`.

## Simple Mode / Power Mode

Default adalah `Simple Mode`.

Simple Mode fokus ke input URL, preset, kualitas, format, cek resolusi, download, cancel, queue, status live, dan log ringkas.

Power Mode membuka tab lanjutan:

- Advanced
- Subtitle & Cookies
- Output / FFmpeg
- History

## Queue Context Menu

Klik kanan item queue untuk:

- Open File
- Open Folder
- Copy Output Path
- Copy URL
- Retry
- Remove from Queue
- Clear Completed

Remove from Queue hanya menghapus item dari queue, bukan file fisik.

## History v2

History v2 memakai `yt_downloader_v2_history.jsonl`.

Tab History menyediakan search, filter `All`, `Done`, `Failed`, `Video`, `Audio`, `YouTube`, `TikTok`, `Instagram`, `Twitter-X`, `Other`, serta action:

- Open File
- Open Folder
- Copy URL
- Re-download
- Clear History

## Clean Temp Files

Tombol `Clean Temp Files` ada di tab Output / FFmpeg.

File yang dibersihkan:

- `*.part`
- `*.ytdl`
- `*.temp`
- `*.tmp`

Pembersihan hanya berjalan di folder output v2 dan tidak boleh berjalan saat status aktif seperti Downloading, Merging, Post-processing, atau Moving final file.


## Social Platform Support

Aplikasi bisa menerima link TikTok, Instagram, dan X/Twitter selain YouTube. Cek resolusi memakai tombol `Cek Resolusi`, dan download memakai engine `yt-dlp` yang sama.

Tombol `Test Link` hanya mengecek metadata singkat dan tidak memasukkan item ke queue. Gunakan ini untuk memastikan link publik/private bisa dibaca sebelum memilih format.

Jika platform sorting aktif, hasil TikTok otomatis masuk ke:

```text
Downloads/
  TikTok/
    Video/
  Instagram/
    Video/
  Twitter-X/
    Video/
```

Platform sosial biasanya menyediakan resolusi terbatas seperti 720p/1080p tergantung source dan hasil ekstraksi `yt-dlp`. Jika TikTok, Instagram, atau X/Twitter error, coba `Update yt-dlp`, gunakan cookies browser, atau gunakan `cookies.txt`. Untuk post private, age-restricted, atau akun yang perlu login, pastikan browser sumber cookies sudah login.

## Platform Folder Sorting

Jika `Pisah folder berdasarkan platform` aktif, output memakai struktur:

```text
Downloads/
  YouTube/
    Video/
    Audio/
  TikTok/
    Video/
    Audio/
  Instagram/
    Video/
    Audio/
  Twitter-X/
    Video/
    Audio/
  Other/
    Video/
    Audio/
```

Jika opsi ini dimatikan, aplikasi kembali memakai logic output lama. Jika `Pisah folder Audio / Video` juga aktif, folder media type tetap dibuat di dalam folder platform.

## FFmpeg

FFmpeg dibutuhkan untuk merge video/audio, convert audio, subtitle, thumbnail, dan metadata.

Aplikasi mencoba auto-detect:

- `ffmpeg.exe` di folder aplikasi
- PATH sistem
- instalasi WinGet FFmpeg

Jika tidak terdeteksi, isi path manual di tab Output / FFmpeg.

## Cookies

Cookies tersedia di tab Subtitle & Cookies untuk video yang membutuhkan sesi browser, login, age restriction, atau terkena rate limit.

Instagram, X/Twitter, dan TikTok lebih sering membutuhkan cookies dibanding YouTube. Pilih Chrome, Edge, Firefox, atau file `cookies.txt` dari browser yang sudah login.

## Subtitle

Mode subtitle:

- Off
- Manual only
- Auto only
- Manual + Auto

Jika `Subtitle optional` aktif, download video tetap dicoba walaupun subtitle gagal.

## Large File / 4K / 8K Merge

Download 4K/8K sering memakai video dan audio terpisah.
FFmpeg perlu merge jadi file final.
File besar seperti 20GB+ bisa lama saat merge.
Pastikan storage kosong minimal 2x ukuran file.
Jangan tutup aplikasi saat status Merging.
MKV direkomendasikan untuk 4K/8K.

Saat estimasi file besar tersedia, v2 menampilkan warning:

- lebih dari 5GB: download dan merge mungkin lebih lama
- lebih dari 10GB: pastikan free storage cukup

Sebelum download file sangat besar, v2 mengecek free space dan merekomendasikan sekitar 2.5x estimasi ukuran file.

## Build EXE v2

Jalankan:

```powershell
.\build_v2.ps1
```

Output:

```text
dist\YouTube Downloader GUI v2.exe
```

Spec v2:

```text
YouTube Downloader GUI v2.spec
```

Build ini tidak menimpa `dist\YouTube Downloader.exe` milik v1.

## Troubleshooting

### App terlihat stuck di 100%

Itu biasanya tahap merge FFmpeg. Tunggu sampai status `Done` dan final file muncul.

### Merge lama

Cek disk usage, FFmpeg process, dan free storage. File 4K/8K besar bisa membutuhkan beberapa menit atau lebih tergantung disk speed.

### Final output path Unknown

Download tetap bisa selesai, tetapi yt-dlp tidak selalu mengembalikan path final. Cek folder output atau gunakan Open Folder.

### Storage warning muncul

Pastikan drive output punya free space cukup. Untuk file besar, sediakan minimal 2x ukuran file, lebih aman 2.5x.


### Platform sosial hanya muncul 720p

Itu berarti format yang tersedia dari platform/yt-dlp untuk video tersebut memang hanya 720p atau yang berhasil diekstrak hanya 720p.

### TikTok/Instagram/X gagal karena challenge/cookies

Update yt-dlp, gunakan cookies browser, atau cookies.txt. Platform sosial kadang memakai challenge, login, age gate, atau proteksi private account yang membutuhkan cookies atau versi yt-dlp terbaru.

## Changelog v2.0.0

- Folder v2 terpisah dari v1.
- File state/history/settings v2 terpisah.
- Window title menjadi Video Downloader GUI v2.
- Simple Mode dan Power Mode.
- Preset profile.
- Live speed/ETA status.
- Queue Speed dan ETA columns.
- Status Merging/Post-processing/Moving final file.
- Postprocessor hooks dan logger parser untuk FFmpeg.
- Final output path disimpan setelah post-processing selesai.
- Large file warning dan disk space check.
- Cancel confirmation saat merge.
- Queue context menu.
- Windows notification via system tray.
- About dialog.
- Clean Temp Files.
- History v2 dengan search/filter/actions.
- Recovery item running menjadi Interrupted setelah app ditutup.
- Instagram dan X/Twitter support via yt-dlp, termasuk deteksi platform, folder sorting, history filter, dan pesan cookies.
- Tombol Test Link untuk cek metadata tanpa memasukkan item ke queue.
- Format `Image` untuk mengambil gambar/thumbnail resolusi tertinggi yang tersedia dari YouTube, TikTok, Instagram, dan X/Twitter.
