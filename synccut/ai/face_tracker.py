import cv2
import numpy as np
import onnxruntime as ort
import os
import librosa

class ActiveSpeakerDetector:
    def __init__(self, model_path: str):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"ONNX model not found at {model_path}")
            
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
        self.session = ort.InferenceSession(
            model_path,
            sess_options=sess_options,
            providers=['CPUExecutionProvider']
        )
        
        # OpenCV Haar Cascade for face detection
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )

    def detect_faces(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, 1.1, 4)
        return faces

    def predict_speaking_sequence(self, visual_frames: np.ndarray, audio_features: np.ndarray):
        """
        Takes a sequence of 25 video frames and 100 audio MFCC frames.
        Returns the logits for the sequence. Speaking score is logit[:, 1].
        """
        # Ensure shapes are correct: (1, T, 112, 112) and (1, T*4, 13)
        visual_input = visual_frames.astype(np.float32)
        audio_input = audio_features.astype(np.float32)

        outputs = self.session.run(None, {
            'audio_input': audio_input,
            'visual_input': visual_input
        })
        
        # Output shape is (T, 2). Apply softmax to get probability of speaking.
        logits = outputs[0] # Shape: (25, 2)
        exp_logits = np.exp(logits - np.max(logits, axis=1, keepdims=True))
        probs = exp_logits / np.sum(exp_logits, axis=1, keepdims=True)
        
        # Return the probability of the "speaking" class (index 1) for each frame
        return probs[:, 1] 