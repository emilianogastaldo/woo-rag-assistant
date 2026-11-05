# Illustrazioni del catalogo Trama

Sei illustrazioni originali create per questa demo il 4 novembre 2026 con
Codex, disegnando forme vettoriali locali. Nessuna fotografia, marchio,
immagine esterna o asset scaricato; nessun generatore bitmap AI.

I sorgenti modificabili sono in `source/*.svg`; i corrispondenti PNG sono
gli unici file importati nella libreria media WordPress. Non occorre
abilitare upload SVG. Tutte le immagini misurano 800 × 800 pixel, con sfondo
carta `#F6F3EC`, tratti inchiostro `#182922`, verde `#315C49` e terracotta
`#AD593F`. Il peso complessivo dei PNG è circa 124 KiB.

Le immagini sono rappresentazioni illustrative dei prodotti fittizi, non
fotografie né garanzie sui colori effettivi. I testi prodotto restano nel CSV;
`products.json` associa SKU, file, testo alternativo e categoria. Le categorie
sono Abbigliamento (`abbigliamento`), Scarpe (`scarpe`) e Accessori (`accessori`).

## Condizioni d'uso

Questi sei asset originali (SVG e PNG) sono dedicati al pubblico dominio con
[CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/).
È consentito copiarli, modificarli e distribuirli, anche per uso commerciale,
senza attribuzione obbligatoria. Non sono inclusi materiali di terzi.

## Rigenerare un PNG

Dalla radice del progetto, con FFmpeg compilato con il decoder librsvg:

```bash
ffmpeg -loglevel error -y -i seed/assets/source/tshirt-bio.svg \
  -frames:v 1 -compression_level 9 seed/assets/tshirt-bio.png
```

Ripetere il comando per ciascun sorgente modificato. FFmpeg è uno strumento di
preparazione locale: il setup della demo usa i PNG già versionati e non lo richiede.
