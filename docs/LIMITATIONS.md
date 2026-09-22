# SyncCut System Limitations & Known Edge Cases

## 1. Acoustic Requirements
- **Complete Inaudibility**: If a camera audio track is completely silent or dominated entirely by uncorrelated out-of-band electronic noise, GCC-PHAT cannot detect timing phase alignment.
- **Extreme Reverberation**: Very heavy acoustic reflections in large concrete spaces broaden cross-correlation peaks, lowering confidence scores.

## 2. Hardware & Media Constraints
- **Variable Frame Rate (VFR)**: Mobile phone recordings with unstable frame rates require constant frame rate (CFR) transcoding prior to frame-exact NLE placement.
- **Extreme Sample Rate Differences**: Audio recorded at non-standard sample rates ($22.05\text{ kHz}$) is automatically resampled to $16\text{ kHz}$; severe spectral aliasing in poorly resampled source files can impact precision.

## 3. Active Speaker Rough Cut
- **Multi-Speaker Overlap**: When two speakers talk simultaneously at identical audio volumes, the active speaker decision falls back to primary channel precedence or previous shot hold.
