# To-Dos

## Bugs to be fixed


## Features to be implemented

### ~~songs, regions and chords from memory~~ ✓ (already read from in-memory timeline)

### ~~time signatures in a separate thread with 1/s update frequency~~ ✓

- MeterMap built during scan (time-sig + tempo at every song/section position)
- Slow-poll thread (1 Hz) keeps tempo + time signature updated from Ableton
- Poll tick reduced from 4 to 2 OSC queries (position + is_playing only)

### CI / CD