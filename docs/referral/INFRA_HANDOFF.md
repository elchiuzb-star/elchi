# Referral havolasi `/r/<kod>` — infra topshirig‘i (5-bosqich, Q107)

**Kimga:** infra mas’uli (ism tayinlanmagan — bu hujjat shaxsni ko‘rsatmaydi).
**Holat:** topshiriq tayyor; **hech narsa deploy qilinmagan, haqiqiy muhitda tekshirilmagan.** Bu hujjat deploy uchun
ruxsat emas — deploy alohida qaror bilan.

## 1. Nima kerak
Mijoz yoki haydovchi `https://<HOST>/r/<KOD>` havolasini ochganda:
- ilova o‘rnatilgan va App Links tasdiqlangan bo‘lsa — ilova ochiladi (Android qismi: `APP_LINKS_HANDOFF.md`);
- aks holda brauzerda statik tushuntirish sahifasi (`landing/r.html`) ochiladi: kodni ko‘rsatadi, nusxalash tugmasi va
  «ilovada qo‘lda kiriting» ko‘rsatmasi. Sahifa hech qanday tarmoq so‘rovi yubormaydi, `noindex`, `no-referrer`.

## 2. Ochiq kiritmalar (o‘ylab topilmaydi)
| Kiritma | Hozirgi dalil | Kim hal qiladi |
|---|---|---|
| `<HOST>` domeni | Q107: `elchigo.uz` — qaror; egalik, registrator va DNS boshqaruvi tekshirilmagan | domen egasi |
| Statik fayllar qayerda | `landing/vercel.json` (Vercel) bor, lekin K3: stage-2 production faqat O‘zbekistondagi hostingda | mahsulot egasi (K3 talqini) |
| API manzili | `Caddyfile`: `{$ELCHI_DOMAIN:api.elchigo.uz}` | infra |

## 3. DNS
- `<HOST>` uchun `A`/`AAAA` (yoki hosting talab qilsa `CNAME`) — statik fayllarni xizmat qiladigan serverga.
- TTL: ishga tushirishda past (masalan 300 s), barqarorlashgach oshiriladi.
- API domeni (`api.<...>`) bu o‘zgarishdan ta’sirlanmaydi.

## 4. TLS
- Faqat HTTPS; HTTP → HTTPS redirect. **`/.well-known/assetlinks.json` redirect qilinmaydi** (Android tekshiruvi
  redirect’ni qabul qilmaydi) va to‘g‘ridan-to‘g‘ri 200 qaytaradi.
- Caddy varianti: sertifikat ACME orqali avtomatik (mavjud `Caddyfile` naqshi, ADR-0011: DNS provayder API’si shart emas).

## 5. Statik fayllar va `/r/<kod>` rewrite
Xizmat qilinadigan fayllar (`landing/`): `r.html`, `styles.css` (+ mavjud `index.html`, `privacy.html`,
`delete-account.html`). `/.well-known/assetlinks.json` — Android egasi qiymatlarni bergandan keyin qo‘shiladi.

**Variant A — Vercel** (repo’dagi konfiguratsiya, K3 hal qilinsa): `landing/vercel.json` allaqachon
`/r/:code → /r.html` rewrite va xavfsizlik header’larini beradi.

**Variant B — O‘zbekistondagi host, Caddy** (K3 bilan mos). Namuna (repo’dagi `Caddyfile` ga **qo‘shilmagan**):
```caddyfile
{$ELCHI_LINK_HOST} {
	encode zstd gzip
	root * /srv/landing
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options "nosniff"
		X-Frame-Options "DENY"
		Referrer-Policy "no-referrer"
		-Server
	}
	@assetlinks path /.well-known/assetlinks.json
	header @assetlinks Content-Type "application/json"
	rewrite /r/* /r.html
	file_server
}
```
`/srv/landing` — `landing/` papkasining nusxasi (faqat statik fayllar; `.env` yoki boshqa repo fayllari emas).

## 6. API tomoni
Faqat havola tekshirilgandan keyin API muhitiga `ELCHI_REFERRAL_LINK_HOST=<HOST>` beriladi. Bo‘sh bo‘lsa
`share_url = null` (QR ko‘rsatilmaydi, kodni nusxalash va qo‘lda kiritish ishlaydi). `promotions_enabled`
production’da **o‘chiq qoladi** — bu topshiriq uni yoqmaydi.

## 7. Tekshirish buyruqlari (natijalar hisobotga ilova qilinadi)
```bash
dig +short <HOST> A; dig +short <HOST> AAAA
curl -sSI https://<HOST>/r/AB2CD3EF            # 200, content-type: text/html, redirect yo'q
curl -sS  https://<HOST>/r/AB2CD3EF | grep -c 'Kodni'            # sahifa matni
curl -sSI http://<HOST>/r/AB2CD3EF             # 301/308 -> https
curl -sSI https://<HOST>/.well-known/assetlinks.json   # 200, application/json, redirect yo'q
curl -sS  https://<HOST>/.well-known/assetlinks.json | python -m json.tool
echo | openssl s_client -connect <HOST>:443 -servername <HOST> 2>/dev/null | openssl x509 -noout -subject -issuer -dates
curl -sS "https://digitalassetlinks.googleapis.com/v1/statements:list?source.web.site=https://<HOST>&relation=delegate_permission/common.handle_all_urls"
```
Brauzerda: DevTools → Network — `r.html` ochilganda tashqi so‘rov yo‘q; `referrer` yuborilmaydi.

## 8. Rollback (DB o‘zgarishi yo‘q)
1. API: `ELCHI_REFERRAL_LINK_HOST` ni olib tashlash → `share_url = null`, ilovada QR yo‘qoladi, kod qo‘lda ishlaydi.
2. `assetlinks.json` ni olib tashlash → yangi o‘rnatishlarda havola ilovani avtomatik ochmaydi (brauzerdagi sahifa qoladi).
3. Site block / Vercel deploy’ni oldingi holatga qaytarish; DNS yozuvini olib tashlash.
Hech bir qadam bron, bonus yoki pul ma’lumotiga tegmaydi.

## 9. «Tayyor» deyish sharti
DNS + TLS + `/r/<kod>` 200 + `assetlinks.json` 200 (redirect’siz) + Digital Asset Links javobi + Android qurilmada
tekshiruv (`APP_LINKS_HANDOFF.md`) — hammasi dalil bilan. Ungacha havola «ishlayapti» deb yozilmaydi; QR yaratilgani
bunga dalil emas.
