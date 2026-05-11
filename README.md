# Daily Corners Predictor ⚽ — (egyelőre csak) Premier League Szöglet Előrejelző

Statisztikai modell alapján előrejelzi az Premier League mérkőzések várható szögletszámát.

## Adatforrás

[football-data.co.uk](https://www.football-data.co.uk/) — ingyenes, nyilvános PL szezononkénti CSV-k.

## Beállítás (egyszeri)

### 1. Repo létrehozása

```bash
git clone https://github.com/FELHASZNALONEV/corner-prophet
cd corner-prophet
```

### 2. Mappák létrehozása és adatok letöltése

```bash
mkdir data
curl -o data/E0_2425.csv https://www.football-data.co.uk/mmz4281/2425/E0.csv
curl -o data/E0_2324.csv https://www.football-data.co.uk/mmz4281/2324/E0.csv
curl -o data/E0_2223.csv https://www.football-data.co.uk/mmz4281/2223/E0.csv
```

### 3. GitHub Pages bekapcsolása

`Settings → Pages → Branch: main → / (root) → Save`

Az oldal elérhető lesz: `https://FELHASZNALONEV.github.io/corner-prophet/`

### 4. Automatikus frissítés (opcionális)

A `.github/workflows/update-data.yml` fájl minden héten automatikusan frissíti a CSV-ket.

## Projekt struktúra

```
corner-prophet/
├── index.html               # Az előrejelző oldal (főoldal)
├── data/
│   ├── E0_2425.csv          # Premier League 2024/25
│   ├── E0_2324.csv          # Premier League 2023/24
│   └── E0_2223.csv          # Premier League 2022/23
├── .github/
│   └── workflows/
│       └── update-data.yml  # Automatikus adat-frissítés
└── README.md
```

## Modell leírása

**Attack/Defense Index (Dixon-Coles ihlet):**

```
Várható hazai szögletek = Liga_átlag × Hazai_támadó_index × Vendég_védelmi_index
Várható vendég szögletek = Liga_átlag × Vendég_támadó_index × Hazai_védelmi_index
```

- **Támadó index**: Csapat szöglet-átlaga / Liga szöglet-átlag
- **Védelmi index**: Csapattal szemben kapott szögletek / Liga átlag
- Súlyozott átlag (lineáris vagy exponenciális) az utolsó N meccs alapján

## Jövőbeli fejlesztések (v0.2+)

- [ ] Poisson eloszlás alapú valószínűségek
- [ ] Több liga (Bundesliga, La Liga stb.)
- [ ] Mérkőzés-keresés (közelgő PL meccsek)
- [ ] Több szezon visszamenőleg (5+ év)

## Adatlicenc

Az adatok [football-data.co.uk](https://www.football-data.co.uk/) tulajdona. Csak személyes, nem kereskedelmi célra.
