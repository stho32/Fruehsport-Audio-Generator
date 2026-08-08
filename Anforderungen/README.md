# Anforderungen

## Nummernschema

Anforderungen werden im Format `RXXXXX-kurzname.md` benannt:

- **R** = Requirement (Anforderung)
- **XXXXX** = Fortlaufende 5-stellige Nummer (z.B. 00001, 00002, ...)
- **kurzname** = Sprechender Kurzname in Kebab-Case

Jede Anforderungsdatei beginnt mit YAML-Frontmatter:

```yaml
---
id: RXXXXX
title: Titel der Anforderung
type: feature | bugfix | refactoring
status: draft | in-progress | done
created: YYYY-MM-DD
---
```

## Uebersicht

| ID     | Titel                       | Typ     | Status |
|--------|-----------------------------|---------|--------|
| R00001 | Fruehsport-Audio-Generator  | feature | done   |
| R00002 | Podcast-Player CLI mit robustem Spotify-Ducking | feature | done   |
