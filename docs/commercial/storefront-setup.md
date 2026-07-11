# Storefront setup (Lemon Squeezy / Paddle / Gumroad)

ShowAble is sold as a **direct download** with license keys. The Mac App Store is not recommended for this architecture.

## Recommended: Lemon Squeezy

1. Create a Lemon Squeezy account and store.
2. Add a product: **ShowAble** — one-time purchase, €49 / $49.
3. Enable **license keys** on the product.
4. Set the delivery email template to include:
   - Download link (macOS zip from your CDN)
   - License key (`SA-XXXX-XXXX-XXXX` format)
   - Link to `docs/commercial/user-guide.md`
5. Configure webhooks (optional) for purchase notifications.

Lemon Squeezy acts as **Merchant of Record** and handles EU VAT.

## Paddle / Gumroad

Same flow: one-time product, license key per purchase, download link in receipt email.

## Generating license keys

Use the bundled generator (set `SHOWABLE_LICENSE_SECRET` in production):

```bash
SHOWABLE_LICENSE_SECRET='your-production-secret' python -c \
  "from engine.licensing import generate_license_key; print(generate_license_key())"
```

For Lemon Squeezy, map generated keys to products or use their native key generation and import keys signed with your secret via a small script.

## Pricing

| Phase | Price |
|-------|-------|
| Early adopter | €39 / $39 |
| Launch | €49 / $49 |
| After v1.0 stable | €69 / $69 |

One-time perpetual license. Optional paid major-version upgrades later.
