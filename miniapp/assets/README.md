# Mini App background photos

Drop a photo here to get the cinematic background wired up by `theme.css`:

| File | Used in | Suggested look |
|------|---------|----------------|
| `bg-day.jpg` | Mini App background | Twilight / blue hour, slight warm horizon |

## Sizing

- **Resolution**: 2000×1300 or larger (covers high-DPI viewports without blur)
- **Format**: JPEG at quality 85 (~250–500 KB) is the sweet spot for mobile load
- **Aspect**: portrait crops work too — `background-size: cover` will scale either way

## Source

Use **license-free** images only:

- [Unsplash](https://unsplash.com/s/photos/tashkent) — CC0, no attribution needed
- [Pexels](https://www.pexels.com/search/tashkent) — free for commercial use
- [Wikimedia Commons](https://commons.wikimedia.org/wiki/Category:Tashkent) — usually CC BY-SA, attribute the photographer

Do **not** drop in stock photos with iStock / Shutterstock / Adobe Stock watermarks — those require a paid licence.

## After dropping the files

1. `git add miniapp/assets/bg-day.jpg`
2. `git commit -m "Add background photos"`
3. `git push origin main`
4. On the server: `git pull && sudo systemctl restart assistant-bot`

The CSS already references these paths — the next page load picks them up automatically.
