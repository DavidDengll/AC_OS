# emotion.py
import datetime
import json
import os
from config import (
    EMOTION_DECAY_RATE,
    EMOTION_SPEAK_ENERGY_COST,
    EMOTION_SILENCE_ENERGY_GAIN,
    EMOTION_LEARN_CURIOSITY_GAIN,
    EMOTION_LEARN_PLEASURE_GAIN,
    EMOTION_UNKNOWN_CURIOSITY_GAIN,
    EMOTION_QUESTION_CURIOSITY_COST
)

EMOTION_STATE_FILE = "emotion_state.json"

class Emotion:
    def __init__(self):
        self.energy = 0.7
        self.curiosity = 0.5
        self.pleasure = 0.5
        self.last_update = datetime.datetime.now().isoformat()
        self.load_state()

    def update(self, event_type=None):
        now = datetime.datetime.now()
        last = datetime.datetime.fromisoformat(self.last_update)
        elapsed_hours = (now - last).total_seconds() / 3600.0

        decay = EMOTION_DECAY_RATE * elapsed_hours
        # Fatigue: increase decay when pleasure high
        fatigue_decay = decay * (1 + self.pleasure)
        self.energy = max(0.0, self.energy - fatigue_decay)
        self.curiosity = max(0.1, self.curiosity - decay * 0.5)
        self.pleasure = max(0.1, self.pleasure - decay * 0.3)

        if event_type == "speak":
            self.energy -= EMOTION_SPEAK_ENERGY_COST
            # curiosity gain with fatigue
            self.curiosity = min(1.0, self.curiosity + 0.02 * (1 - self.curiosity))
        elif event_type == "silence":
            self.energy = min(1.0, self.energy + EMOTION_SILENCE_ENERGY_GAIN)
        elif event_type == "learn_new":
            # fatigue on curiosity and pleasure gains
            self.curiosity = min(1.0, self.curiosity + EMOTION_LEARN_CURIOSITY_GAIN * (1 - self.curiosity))
            self.pleasure = min(1.0, self.pleasure + EMOTION_LEARN_PLEASURE_GAIN * (1 - self.pleasure))
        elif event_type == "unknown_streak":
            self.curiosity = min(1.0, self.curiosity + EMOTION_UNKNOWN_CURIOSITY_GAIN * (1 - self.curiosity))
            self.energy -= 0.02
        elif event_type == "question_asked":
            self.curiosity -= EMOTION_QUESTION_CURIOSITY_COST
            self.pleasure = min(1.0, self.pleasure + 0.05 * (1 - self.pleasure))

        self.energy = max(0.0, min(1.0, self.energy))
        self.curiosity = max(0.0, min(1.0, self.curiosity))
        self.pleasure = max(0.0, min(1.0, self.pleasure))

        self.last_update = now.isoformat()
        self.save_state()

    def get_state(self):
        return {
            "energy": self.energy,
            "curiosity": self.curiosity,
            "pleasure": self.pleasure
        }

    def save_state(self):
        with open(EMOTION_STATE_FILE, 'w') as f:
            json.dump({
                "energy": self.energy,
                "curiosity": self.curiosity,
                "pleasure": self.pleasure,
                "last_update": self.last_update
            }, f)

    def load_state(self):
        if os.path.exists(EMOTION_STATE_FILE):
            with open(EMOTION_STATE_FILE, 'r') as f:
                data = json.load(f)
                self.energy = data.get("energy", self.energy)
                self.curiosity = data.get("curiosity", self.curiosity)
                self.pleasure = data.get("pleasure", self.pleasure)
                self.last_update = data.get("last_update", self.last_update)