# Nuke Comp: збірка layer-branch з 4 Read-нод

**Проект (приклад):** `raid_echoes_of_oz / cinematic / sq010 / sh330`
**Layer у прикладі:** `bg`
**Захоплено:** 2026-08-06, через `nuke_mcp_plugin.py` (`get_nodes_in_view` / `execute_code`), живий скрипт на pc137

---

## TL;DR

Sashok будує комп із **layer-branches** (`fg`, `bg`, `floorVolume`, `atmo`, `clouds`, `dem_debris`, `dem_vol1` тощо). Кожен branch — рівно **4 Read-ноди**, по одній на render pass, які зводяться в один потік:

```
lights_product  ─┐
beauty_product  ─┼─→ (ShuffleCopy chain)  ─→  + tech_product (Copy)  ─→  + crypto_product (Copy, через Cryptomatte)
tech_product    ─┘
crypto_product  ──────────────────────────────────────────────────────────↗
```

- **beauty_product** = rgba + emission
- **tech_product** = Zg, Zc, P, mv (технічні/utility паси)
- **lights_product** = per-light AOV
- **crypto_product** = Cryptomatte-канали

Весь шот-комп — це N таких layer-branches, зведених разом.

---

## Конвенція шляхів

```
//loky.plarium.local/project/_pl/<project>/cinematic/<sequence>/<shot>/render/<layer>/v0XX/<pass>_product.%04d.exr
```

Приклад (layer `bg`):
```
.../raid_echoes_of_oz/cinematic/sq010/sh330/render/bg/v007/beauty_product.%04d.exr
.../raid_echoes_of_oz/cinematic/sq010/sh330/render/bg/v007/lights_product.%04d.exr
.../raid_echoes_of_oz/cinematic/sq010/sh330/render/bg/v006/tech_product.%04d.exr
.../raid_echoes_of_oz/cinematic/sq010/sh330/render/bg/v006/crypto_product.%04d.exr
```

**Важливо:** 4 паси одного "живого" layer-branch не обов'язково однієї версії (тут: beauty/lights=v007, tech/crypto=v006 — різні). Паси рендеряться/перерендеряться незалежно, тож version-swap тулза має керувати версією кожної з 4 Read-нод окремо, не припускаючи, що вони рухаються в лок-степі.

---

## Старі версії не видаляються

У референс-графі лежало 5 *зайвих*, відключених Read-нод (`beauty_product` / `lights_product` на v001, v002, v004, v006) — історія/порівняння, не живі. **Наслідок:** щоб зрозуміти, яка Read жива, треба дивитись що реально йде далі по ланцюгу (`inputs`), а не просто на список нод у графі. Пара таких сирітських Read-нод також живить `LayerContactSheet`-ноду збоку — для візуального порівняння версій поза основним потоком.

---

## Топологія збірки (референс-граф)

```
Read12(lights v007) ─┐
Read35(beauty v007) ─┼→ ShuffleCopy8 → ShuffleCopy1 ─┐
                      ┘                               ├→ Copy18 ─┐
Read2(tech v006)  ─────────────────────────────────────┘         ├→ Copy19  ← Cryptomatte3 ← Dot38 ← Read14(crypto v006)
                                                                   ┘
```

`Copy19` — точка, де всі 4 паси нарешті зведені в один вузол. Злиття всюди йде через **Copy**-ноди (не ChannelMerge — попередній прохід аналізу помилково прочитав ChannelMerge-ноду, яку користувач потім видалив як таку, що плутала аналіз; виправлено 2026-08-06).

## Crypto matte extraction (після Copy19)

Далі від `Copy19` йде ланцюжок `Copy17 → Copy23 → Copy10 → Copy11 → Copy6 → Copy7 → Copy8 → Copy9` — кожен доливає ще одну ізольовану crypto-матовку. Джерело — прямий Dot-спайн від того самого crypto Read:

```
Read14(crypto) → Dot38 → Dot62 → Dot63 → Dot15 → Dot18 → Dot23 → Dot30 → Dot17 → Dot32
                   ↓        ↓       ↓       ↓       ↓        ↓       ↓       ↓       ↓
              Cryptomatte3 6      7       2      11        10       9      5       8
```

9 окремих Cryptomatte-нод, кожна ізолює свій об'єкт/матеріал. `Roto4` вшита в той самий Copy-ланцюг для матовки, яку crypto не бере чисто.

Окремо є два бічні відгалуження (`Copy1`, `Copy12`) — ізольовані прев'ю конкретної crypto-вибірки, не частина основного накопичувального ланцюга.

---

## Навіщо це задокументовано — актуальний запит

Ручна заміна 4 Read-нод на layer-branch (нова версія, фікс рендеру тощо) зараз ручна, і з N branches × 4 Read кожен — це error-prone при масштабуванні на цілий шот. Потрібні:

1. **Ініціалізація нового layer-branch** — скрипт створює 4 Read-ноди + assembly chain (ShuffleCopy → Copy → Cryptomatte-merge) з імені layer.
2. **Version management на існуючих branches** — bump/pin версії, ведення кольору/розташування нод при додаванні нових branches поряд зі старими.

Ще не реалізовано — це референс для майбутньої розробки цих скриптів.
