// GROOVEBOX -- hardware controller for a real multi-track drum
// machine. The R4 itself only does four things: keeps the beat clock
// (BPM from the pot), reads the buttons/BLE, drives the LED matrix
// display, and sends one compact status line over serial every 16th
// note. It has NO pattern data and NO idea what a "kick" or "bass" is
// -- all of that (track list, step grids, notes, MIDI output) lives
// PC-side in groovebox_drum_machine.py, which has a real clickable
// step-grid GUI. That split exists because editing multi-track
// patterns via 6 buttons and a 12x8 matrix would be miserable; a
// screen isn't.
//
// Serial protocol, outgoing (one line per 16th note):
//   STEP:<0-15>,PAT:<0-7>,MUTE:<0-31>,FILL:<0|1>,FX:<0-127>
// PAT is which of 8 pattern slots is selected (cycled by the pattern
// button). MUTE is a 5-bit group mask: bit0=kick,1=snare/clap,
// 2=hats/perc,3=bass,4=lead -- the PC side maps its (larger) track
// list onto these same 5 groups so the 5 physical mute buttons still
// make sense. FILL is set for the last bar of... nothing automatic
// here anymore (song arrangement moved out with the pattern data) --
// it's just "the Fill button was pressed within the last bar." FX is
// the optional A2 pot (see PINS below), sent as a live effects value
// (filter cutoff) -- reads a fixed value even with nothing wired.
//
// Serial protocol, incoming (PC -> board, after each STEP line):
//   HIT:<0-31>
// Same 5-bit group encoding as MUTE, but says which groups actually
// played a note that step (after the PC's own mute/fill logic) --
// drives a brief matrix flash per group. This is the live tie-in
// between what the drum machine is really doing and the display.
//   SWING:<0-75>
// Sets swing amount (see loop() below) -- 0 is straight/quantized,
// higher values push the upbeats later for a groovier, less robotic
// feel, same idea as the TR-909's shuffle. Set from a GUI slider.
//   SETBPM:<60-200>
// Sets tempo directly (tap-tempo from the GUI). The pot still takes
// over as soon as it's physically moved again -- see the comment on
// lastPotBpm at the SETBPM handler for exactly why that works.
//
// Controls:
//   - A1: potentiometer sets BPM (80-160)
//   - D2: cycle pattern slot (0 -> 1 -> ... -> 7 -> 0...)
//   - D3/D4/D6/D7/D8: mute toggle for kick / snare+clap / hats+perc / bass / lead
//   - D9: Fill -- PC side decides what that actually layers in
//   - D5: Start/Stop -- pauses/resumes the sequencer clock; the board
//     simply stops emitting STEP: lines while stopped, so the PC side
//     (and everything downstream of it) naturally goes quiet
//   - BLE peripheral "R4-Groovebox": phone can remotely set pattern
//     slot, BPM, group mutes, and trigger a fill -- same as buttons
//   - Onboard LED matrix: row 7 (bottom) of each group's column is a
//     steady mute/unmute marker, rows 0-5 flash briefly on real hits
//     (HIT: above); a brief letter flash (K/S/H/B/L/F, 1/2/3/4) also
//     overlays on every button/BLE action
//   - 12-LED NeoPixel ring (D13): same HIT: data drives a live 5-color
//     light show -- kick=red, snare=yellow, hat=cyan, bass=purple,
//     lead=green, each group gets its own arc of pixels that pulses
//     and fades on every real hit

#include <ArduinoBLE.h>
#include "Arduino_LED_Matrix.h"
#include <Adafruit_NeoPixel.h>

ArduinoLEDMatrix matrix;
uint8_t matrixFrame[8][12];

#define RING_PIN 13
#define RING_COUNT 12
Adafruit_NeoPixel ring(RING_COUNT, RING_PIN, NEO_GRB + NEO_KHZ800);

// Declared here (not down by the matrix display code below) for the
// same reason CustomParams needed moving in the LED Vault firmware:
// Arduino's auto-generated function prototypes are inserted right
// after the last #include, before this enum would otherwise be
// declared -- any function using it in its signature fails to compile
// unless the enum already exists by that point.
enum FlashGlyph { FLASH_NONE, FLASH_K, FLASH_S, FLASH_H, FLASH_B, FLASH_L, FLASH_F, FLASH_1, FLASH_2, FLASH_3, FLASH_4, FLASH_5, FLASH_6, FLASH_7, FLASH_8, FLASH_PLAY, FLASH_STOP };

// ============================================================
// PINS
// ============================================================
#define POT_PIN A1
#define FX_POT_PIN A2  // optional -- wire a second pot here later for a live filter-cutoff knob; reads as a steady value even unconnected once smoothed
#define BTN_NEXT_PATTERN 2
#define BTN_MUTE_KICK 3
#define BTN_MUTE_SNARE 4
#define BTN_MUTE_HAT 6
#define BTN_MUTE_BASS 7
#define BTN_MUTE_LEAD 8
#define BTN_FILL 9
#define BTN_STOP 5  // free since the ring moved to D13

const int NUM_PATTERN_SLOTS = 8;

// ============================================================
// BLE
// ============================================================
BLEService groovebox("19b10000-e8f2-537e-4f6c-d104768a1214");
BLEByteCharacteristic patternChar("19b10001-e8f2-537e-4f6c-d104768a1214", BLERead | BLEWrite);
BLEByteCharacteristic bpmChar("19b10002-e8f2-537e-4f6c-d104768a1214", BLERead | BLEWrite);
BLEByteCharacteristic muteChar("19b10003-e8f2-537e-4f6c-d104768a1214", BLERead | BLEWrite);
BLEByteCharacteristic fillChar("19b10004-e8f2-537e-4f6c-d104768a1214", BLERead | BLEWrite);  // any non-zero write triggers a fill

// ============================================================
// CLOCK/CONTROL STATE
// ============================================================
int bpm = 128;
int lastPotBpm = -1;
int fxValue = 0;      // 0-127, sent to the PC as a live effects (filter cutoff) control
int lastFxValue = -1;
int patternSlot = 0;
uint8_t muteMask = 0;  // bit0=kick,1=snare/clap,2=hats/perc,3=bass,4=lead
int currentStep = 0;
unsigned long stepStartMillis = 0;
bool fillActive = false;  // true for exactly one bar after the Fill button/BLE trigger
int swingPercent = 12;    // 0=straight, up to ~75=heavy swing; set from the GUI via SWING:<n>
bool running = true;      // BTN_STOP toggles this; sequencer simply stops emitting STEP: lines when false

void advanceStep() {
  Serial.print("STEP:");
  Serial.print(currentStep);
  Serial.print(",PAT:");
  Serial.print(patternSlot);
  Serial.print(",MUTE:");
  Serial.print(muteMask);
  Serial.print(",FILL:");
  Serial.print(fillActive ? 1 : 0);
  Serial.print(",FX:");
  Serial.println(fxValue);

  currentStep = (currentStep + 1) % 16;
  if (currentStep == 0) fillActive = false;  // fill lasts exactly one bar
}

// ============================================================
// INCOMING SERIAL -- the PC sends "HIT:<5-bit mask>" back after each
// step, saying which of the 5 groups actually played a note that
// step (after its own mute/fill logic). Drives a brief matrix flash
// AND a NeoPixel ring pulse per group -- this is what actually ties
// the drum machine's real activity into both displays, not just
// static mute state.
// ============================================================
String incomingLine = "";
unsigned long groupHitUntil[5] = {0, 0, 0, 0, 0};
const unsigned long HIT_FLASH_MS = 60;

// Ring: 12 pixels split into 5 colored segments, one per group.
// kick=2, snare=2, hat=3 (busiest group, extra pixel), bass=2, lead=3.
const int GROUP_PIXEL_START[5] = {0, 2, 4, 7, 9};
const int GROUP_PIXEL_COUNT[5] = {2, 2, 3, 2, 3};
const uint32_t GROUP_COLOR[5] = {
  0xFF0000,  // kick   -- red
  0xFFC800,  // snare  -- yellow
  0x00C8FF,  // hat    -- cyan
  0xB400FF,  // bass   -- purple
  0x00FF50,  // lead   -- green
};
float ringBrightness[5] = {0, 0, 0, 0, 0};
const float RING_DECAY = 0.90f;  // ~100-150ms fade per pulse

void updateRing() {
  for (int g = 0; g < 5; g++) {
    ringBrightness[g] *= RING_DECAY;
    if (ringBrightness[g] < 0.01f) ringBrightness[g] = 0;
    uint8_t r = (uint8_t)(((GROUP_COLOR[g] >> 16) & 0xFF) * ringBrightness[g]);
    uint8_t g8 = (uint8_t)(((GROUP_COLOR[g] >> 8) & 0xFF) * ringBrightness[g]);
    uint8_t b = (uint8_t)((GROUP_COLOR[g] & 0xFF) * ringBrightness[g]);
    for (int i = 0; i < GROUP_PIXEL_COUNT[g]; i++) {
      ring.setPixelColor(GROUP_PIXEL_START[g] + i, r, g8, b);
    }
  }
  ring.show();
}

void checkIncoming() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      incomingLine.trim();
      if (incomingLine.startsWith("HIT:")) {
        int mask = incomingLine.substring(4).toInt();
        unsigned long until = millis() + HIT_FLASH_MS;
        for (int g = 0; g < 5; g++) {
          if (mask & (1 << g)) {
            groupHitUntil[g] = until;
            ringBrightness[g] = 1.0f;
          }
        }
      } else if (incomingLine.startsWith("SWING:")) {
        swingPercent = constrain(incomingLine.substring(6).toInt(), 0, 75);
      } else if (incomingLine.startsWith("SETBPM:")) {
        // Deliberately does NOT touch lastPotBpm -- that tracks the
        // pot's own last physical reading, independent of bpm itself.
        // Leaving it alone means this only gets overridden once the
        // pot is actually moved again, not on the next read regardless.
        bpm = constrain(incomingLine.substring(7).toInt(), 60, 200);
      }
      incomingLine = "";
    } else if (c != '\r') {
      incomingLine += c;
    }
  }
}

// ============================================================
// CONTROLS -- buttons (debounced), pot, BLE.
// ============================================================
unsigned long lastButtonMillis[8] = {0, 0, 0, 0, 0, 0, 0, 0};
bool lastButtonState[8] = {HIGH, HIGH, HIGH, HIGH, HIGH, HIGH, HIGH, HIGH};
const unsigned long DEBOUNCE_MS = 200;

// Edge-triggered on the HIGH->LOW transition, not just "is currently
// LOW" -- a pin that's stuck LOW (e.g. a button wired with two legs
// from the same side instead of diagonal, which shorts the pin to GND
// permanently) fires this once and then never again, instead of
// re-firing every DEBOUNCE_MS forever.
bool buttonPressed(int pin, int idx) {
  bool state = digitalRead(pin);
  bool pressed = false;
  if (state == LOW && lastButtonState[idx] == HIGH && millis() - lastButtonMillis[idx] > DEBOUNCE_MS) {
    pressed = true;
    lastButtonMillis[idx] = millis();
  }
  lastButtonState[idx] = state;
  return pressed;
}

// ============================================================
// MATRIX DISPLAY -- two modes, both non-blocking (no ArduinoGraphics
// scrolling text here -- that blocks for a couple seconds, which
// would stall the beat clock). Persistent view: one column per group,
// lit = playing, dark = muted, plus a 1/2/3/4-dot pattern-slot
// counter. Flash view: whenever a button/BLE write actually does
// something, briefly (600ms) show a big letter/number identifying
// which control it was, then automatically revert.
// ============================================================
const uint8_t GLYPH_K[7][5] = {{1,0,0,0,1},{1,0,0,1,0},{1,0,1,0,0},{1,1,0,0,0},{1,0,1,0,0},{1,0,0,1,0},{1,0,0,0,1}};
const uint8_t GLYPH_S[7][5] = {{0,1,1,1,1},{1,0,0,0,0},{1,0,0,0,0},{0,1,1,1,0},{0,0,0,0,1},{0,0,0,0,1},{1,1,1,1,0}};
const uint8_t GLYPH_H[7][5] = {{1,0,0,0,1},{1,0,0,0,1},{1,0,0,0,1},{1,1,1,1,1},{1,0,0,0,1},{1,0,0,0,1},{1,0,0,0,1}};
const uint8_t GLYPH_B[7][5] = {{1,1,1,1,0},{1,0,0,0,1},{1,0,0,0,1},{1,1,1,1,0},{1,0,0,0,1},{1,0,0,0,1},{1,1,1,1,0}};
const uint8_t GLYPH_L[7][5] = {{1,0,0,0,0},{1,0,0,0,0},{1,0,0,0,0},{1,0,0,0,0},{1,0,0,0,0},{1,0,0,0,0},{1,1,1,1,1}};
const uint8_t GLYPH_F[7][5] = {{1,1,1,1,1},{1,0,0,0,0},{1,0,0,0,0},{1,1,1,1,0},{1,0,0,0,0},{1,0,0,0,0},{1,0,0,0,0}};
const uint8_t GLYPH_1[7][5] = {{0,0,1,0,0},{0,1,1,0,0},{0,0,1,0,0},{0,0,1,0,0},{0,0,1,0,0},{0,0,1,0,0},{0,1,1,1,0}};
const uint8_t GLYPH_2[7][5] = {{0,1,1,1,0},{1,0,0,0,1},{0,0,0,0,1},{0,0,0,1,0},{0,0,1,0,0},{0,1,0,0,0},{1,1,1,1,1}};
const uint8_t GLYPH_3[7][5] = {{0,1,1,1,0},{1,0,0,0,1},{0,0,0,0,1},{0,0,1,1,0},{0,0,0,0,1},{1,0,0,0,1},{0,1,1,1,0}};
const uint8_t GLYPH_4[7][5] = {{0,0,0,1,0},{0,0,1,1,0},{0,1,0,1,0},{1,0,0,1,0},{1,1,1,1,1},{0,0,0,1,0},{0,0,0,1,0}};
const uint8_t GLYPH_5[7][5] = {{1,1,1,1,1},{1,0,0,0,0},{1,1,1,1,0},{0,0,0,0,1},{0,0,0,0,1},{1,0,0,0,1},{0,1,1,1,0}};
const uint8_t GLYPH_6[7][5] = {{0,0,1,1,0},{0,1,0,0,0},{1,0,0,0,0},{1,1,1,1,0},{1,0,0,0,1},{1,0,0,0,1},{0,1,1,1,0}};
const uint8_t GLYPH_7[7][5] = {{1,1,1,1,1},{0,0,0,0,1},{0,0,0,1,0},{0,0,1,0,0},{0,1,0,0,0},{0,1,0,0,0},{0,1,0,0,0}};
const uint8_t GLYPH_8[7][5] = {{0,1,1,1,0},{1,0,0,0,1},{1,0,0,0,1},{0,1,1,1,0},{1,0,0,0,1},{1,0,0,0,1},{0,1,1,1,0}};
const uint8_t GLYPH_PLAY[7][5] = {{1,0,0,0,0},{1,1,0,0,0},{1,1,1,0,0},{1,1,1,1,0},{1,1,1,0,0},{1,1,0,0,0},{1,0,0,0,0}};
const uint8_t GLYPH_STOP[7][5] = {{0,0,0,0,0},{0,1,1,1,0},{0,1,1,1,0},{0,1,1,1,0},{0,1,1,1,0},{0,1,1,1,0},{0,0,0,0,0}};

FlashGlyph pendingFlash = FLASH_NONE;
unsigned long flashUntilMillis = 0;
const unsigned long FLASH_DURATION_MS = 600;

void startFlash(FlashGlyph g) {
  pendingFlash = g;
  flashUntilMillis = millis() + FLASH_DURATION_MS;
}

void drawGlyph(FlashGlyph g) {
  for (int r = 0; r < 8; r++)
    for (int c = 0; c < 12; c++)
      matrixFrame[r][c] = 0;

  const uint8_t (*glyph)[5] = nullptr;
  switch (g) {
    case FLASH_K: glyph = GLYPH_K; break;
    case FLASH_S: glyph = GLYPH_S; break;
    case FLASH_H: glyph = GLYPH_H; break;
    case FLASH_B: glyph = GLYPH_B; break;
    case FLASH_L: glyph = GLYPH_L; break;
    case FLASH_F: glyph = GLYPH_F; break;
    case FLASH_1: glyph = GLYPH_1; break;
    case FLASH_2: glyph = GLYPH_2; break;
    case FLASH_3: glyph = GLYPH_3; break;
    case FLASH_4: glyph = GLYPH_4; break;
    case FLASH_5: glyph = GLYPH_5; break;
    case FLASH_6: glyph = GLYPH_6; break;
    case FLASH_7: glyph = GLYPH_7; break;
    case FLASH_8: glyph = GLYPH_8; break;
    case FLASH_PLAY: glyph = GLYPH_PLAY; break;
    case FLASH_STOP: glyph = GLYPH_STOP; break;
    default: return;
  }
  for (int r = 0; r < 7; r++)
    for (int c = 0; c < 5; c++)
      matrixFrame[r][3 + c] = glyph[r][c];  // centered: columns 3-7 of 12
}

void updateMatrixDisplay() {
  if (millis() < flashUntilMillis) {
    drawGlyph(pendingFlash);
    matrix.renderBitmap(matrixFrame, 8, 12);
    return;
  }

  for (int r = 0; r < 8; r++)
    for (int c = 0; c < 12; c++)
      matrixFrame[r][c] = 0;

  // Mute status and live hits are kept in physically separate rows so
  // a busy pattern's flashing doesn't swallow the status dots -- row 7
  // (bottom) is a steady unmuted/muted dot per group; rows 0-5 flash
  // briefly (see checkIncoming()/HIT: above) only on an actual hit.
  // Dense patterns can retrigger a flash before the last one clears,
  // but keeping the flash short (60ms, HIT_FLASH_MS above) keeps it
  // reading as a pulse rather than a solid bar even then.
  bool groupActive[5] = {
    !(bool)(muteMask & 0x01),  // kick
    !(bool)(muteMask & 0x02),  // snare + clap
    !(bool)(muteMask & 0x04),  // hats + perc
    !(bool)(muteMask & 0x08),  // bass
    !(bool)(muteMask & 0x10),  // lead
  };
  const int groupCols[5] = {0, 2, 4, 6, 8};
  unsigned long now = millis();
  for (int g = 0; g < 5; g++) {
    matrixFrame[7][groupCols[g]] = groupActive[g] ? 1 : 0;
    if (now < groupHitUntil[g]) {
      for (int r = 0; r < 6; r++) matrixFrame[r][groupCols[g]] = 1;
    }
  }

  // 3x3 grid of dots (columns 9-11, rows 5-7) -- fills row 7 left to
  // right first, then row 6, then row 5, so up to 9 slots each get one
  // dot. Columns 9-11 are otherwise unused by the group hit-flash
  // (that only touches columns 0,2,4,6,8), so no collision.
  int litDots = patternSlot + 1;
  for (int i = 0; i < litDots; i++) {
    int row = 7 - (i / 3);
    int col = 9 + (i % 3);
    matrixFrame[row][col] = 1;
  }

  matrix.renderBitmap(matrixFrame, 8, 12);
}

FlashGlyph patternFlashGlyph() {
  switch (patternSlot) {
    case 0: return FLASH_1;
    case 1: return FLASH_2;
    case 2: return FLASH_3;
    case 3: return FLASH_4;
    case 4: return FLASH_5;
    case 5: return FLASH_6;
    case 6: return FLASH_7;
    default: return FLASH_8;
  }
}

void checkControls() {
  if (buttonPressed(BTN_NEXT_PATTERN, 0)) {
    patternSlot = (patternSlot + 1) % NUM_PATTERN_SLOTS;
    startFlash(patternFlashGlyph());
  }
  if (buttonPressed(BTN_MUTE_KICK, 1))  { muteMask ^= 0x01; startFlash(FLASH_K); }
  if (buttonPressed(BTN_MUTE_SNARE, 2)) { muteMask ^= 0x02; startFlash(FLASH_S); }
  if (buttonPressed(BTN_MUTE_HAT, 3))   { muteMask ^= 0x04; startFlash(FLASH_H); }
  if (buttonPressed(BTN_MUTE_BASS, 4))  { muteMask ^= 0x08; startFlash(FLASH_B); }
  if (buttonPressed(BTN_MUTE_LEAD, 5))  { muteMask ^= 0x10; startFlash(FLASH_L); }
  if (buttonPressed(BTN_FILL, 6))       { fillActive = true; startFlash(FLASH_F); }
  if (buttonPressed(BTN_STOP, 7))       { running = !running; startFlash(running ? FLASH_PLAY : FLASH_STOP); }

  int potRaw = analogRead(POT_PIN);
  int potBpm = map(potRaw, 0, 1023, 80, 160);
  if (abs(potBpm - lastPotBpm) > 1) {
    bpm = potBpm;
    lastPotBpm = potBpm;
  }

  int fxRaw = analogRead(FX_POT_PIN);
  int fxMapped = map(fxRaw, 0, 1023, 0, 127);
  if (abs(fxMapped - lastFxValue) > 1) {
    fxValue = fxMapped;
    lastFxValue = fxMapped;
  }

  BLE.poll();
  if (patternChar.written()) {
    patternSlot = patternChar.value() % NUM_PATTERN_SLOTS;
    startFlash(patternFlashGlyph());
  }
  if (bpmChar.written()) {
    bpm = constrain((int)bpmChar.value(), 60, 200);
  }
  if (muteChar.written()) {
    muteMask = muteChar.value();
  }
  if (fillChar.written() && fillChar.value() != 0) {
    fillActive = true;
    startFlash(FLASH_F);
  }

  updateMatrixDisplay();
}

// ============================================================
// SETUP
// ============================================================
void setup() {
  Serial.begin(115200);
  matrix.begin();
  ring.begin();
  ring.setBrightness(80);  // cap current draw
  ring.clear();
  ring.show();

  pinMode(BTN_NEXT_PATTERN, INPUT_PULLUP);
  pinMode(BTN_MUTE_KICK, INPUT_PULLUP);
  pinMode(BTN_MUTE_SNARE, INPUT_PULLUP);
  pinMode(BTN_MUTE_HAT, INPUT_PULLUP);
  pinMode(BTN_MUTE_BASS, INPUT_PULLUP);
  pinMode(BTN_MUTE_LEAD, INPUT_PULLUP);
  pinMode(BTN_FILL, INPUT_PULLUP);
  pinMode(BTN_STOP, INPUT_PULLUP);

  if (!BLE.begin()) {
    Serial.println("# BLE failed to start -- continuing without it.");
  } else {
    BLE.setLocalName("R4-Groovebox");
    BLE.setAdvertisedService(groovebox);
    groovebox.addCharacteristic(patternChar);
    groovebox.addCharacteristic(bpmChar);
    groovebox.addCharacteristic(muteChar);
    groovebox.addCharacteristic(fillChar);
    BLE.addService(groovebox);
    patternChar.writeValue(0);
    bpmChar.writeValue(bpm);
    muteChar.writeValue(0);
    fillChar.writeValue(0);
    BLE.advertise();
    Serial.println("# BLE advertising as 'R4-Groovebox'.");
  }

  Serial.println("# GROOVEBOX controller ready. Sending step clock over serial.");
  updateMatrixDisplay();
}

// ============================================================
// MAIN LOOP -- plain millis()-based step timing, no sample-accurate
// requirement (that was only ever needed for on-board audio
// synthesis, long gone now).
// ============================================================
void loop() {
  unsigned long now = millis();
  unsigned long baseStepMillis = (60000UL / bpm) / 4;  // 16th note
  // Swing: lengthen the on-beat (even-indexed) steps, which pushes the
  // following upbeat later -- the classic TR-909 shuffle feel. At
  // swingPercent=0 this is identical to straight quantized timing.
  unsigned long stepDurationMillis = baseStepMillis;
  if (currentStep % 2 == 0) {
    stepDurationMillis += (baseStepMillis * swingPercent) / 100;
  }

  if (!running) {
    stepStartMillis = now;  // keep the clock from accumulating a backlog while stopped
  } else if (now - stepStartMillis >= stepDurationMillis) {
    stepStartMillis = now;
    advanceStep();
  }

  checkIncoming();
  checkControls();
  updateRing();
}
