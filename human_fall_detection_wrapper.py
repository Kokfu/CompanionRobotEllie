"""
HumanFallDetection Wrapper for Flask Integration
This module provides a simplified interface to HumanFallDetection-master
that can be integrated directly into the Flask app without ROS2.
"""

import os
import sys
import time
import logging
import numpy as np
import cv2
from typing import Optional, Dict, Any
from collections import deque

# Add HumanFallDetection-master to path
HUMAN_FALL_DETECTION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'HumanFallDetection-master')
if HUMAN_FALL_DETECTION_PATH not in sys.path:
    sys.path.insert(0, HUMAN_FALL_DETECTION_PATH)

try:
    from fall_detector import FallDetector
    HUMAN_FALL_DETECTION_AVAILABLE = True
except ImportError as e:
    logging.warning(f"HumanFallDetection not available: {e}")
    HUMAN_FALL_DETECTION_AVAILABLE = False

class HumanFallDetectionWrapper:
    """
    Wrapper class for HumanFallDetection that provides a simple interface
    for fall detection without requiring ROS2 or command line arguments.
    """
    
    def __init__(self, disable_cuda: bool = True, confidence_threshold: float = 0.7):
        """
        Initialize the HumanFallDetection wrapper.
        
        Args:
            disable_cuda: Whether to disable CUDA (default: True for compatibility)
            confidence_threshold: Confidence threshold for fall detection
        """
        self.available = HUMAN_FALL_DETECTION_AVAILABLE
        self.disable_cuda = disable_cuda
        self.confidence_threshold = confidence_threshold
        self.fall_detector = None
        self.predictor = None
        self.frame_buffer = deque(maxlen=3)  # Keep last 3 frames for temporal analysis
        
        # Fall detection state
        self.consec_fall_like = 0
        self.confirm_frames = 3  # Number of consecutive frames needed for confirmation
        self.last_result = {
            'is_fall': False,
            'confidence': 0.0,
            'angle': 0.0,
            'timestamp': None
        }
        
        if self.available:
            self._initialize_detector()
    
    def _initialize_detector(self):
        """Initialize the HumanFallDetection detector with custom arguments."""
        try:
            # Create a custom FallDetector with our own argument parsing
            self.fall_detector = FallDetector()
            
            # Override the CLI arguments with our custom settings
            args = self.fall_detector.args
            
            # Set our custom parameters
            args.disable_cuda = self.disable_cuda
            args.resolution = 0.4  # Lower resolution for better performance
            args.fall_confirm_sec = 1.0  # 1 second confirmation
            args.fall_aspect = 0.75  # Aspect ratio threshold
            args.fall_tilt_deg = 40.0  # Tilt angle threshold
            args.fps = 10  # Processing FPS
            args.skip = 1  # Process every other frame
            args.no_window = True  # Don't show OpenCV window
            args.joints = False  # Don't draw joints
            args.skeleton = False  # Don't draw skeleton
            args.save_output = False  # Don't save output
            
            # Set device
            if self.disable_cuda or not hasattr(args, 'device'):
                args.device = 'cpu'
            else:
                args.device = 'cuda' if not self.disable_cuda else 'cpu'
            
            # Build predictor
            self._build_predictor()
            
            logging.info("HumanFallDetection wrapper initialized successfully")
            
        except Exception as e:
            logging.error(f"Failed to initialize HumanFallDetection: {e}")
            self.available = False
    
    def _build_predictor(self):
        """Build the OpenPifPaf predictor."""
        try:
            import openpifpaf
            
            # Try to use a lightweight checkpoint
            checkpoint = 'shufflenetv2k16'  # CPU-friendly checkpoint
            
            try:
                self.predictor = openpifpaf.Predictor(checkpoint=checkpoint)
                logging.info(f"Using checkpoint: {checkpoint}")
            except Exception as e:
                logging.warning(f"Checkpoint {checkpoint} failed, trying default: {e}")
                self.predictor = openpifpaf.Predictor()
                
        except Exception as e:
            logging.error(f"Failed to build predictor: {e}")
            self.available = False
    
    def process_frame(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Process a single frame for fall detection.
        
        Args:
            frame: Input frame as numpy array (BGR format)
            
        Returns:
            Dictionary with fall detection results
        """
        if not self.available or self.predictor is None:
            return {
                'is_fall': False,
                'confidence': 0.0,
                'angle': 0.0,
                'timestamp': time.time(),
                'error': 'HumanFallDetection not available'
            }
        
        try:
            # Convert BGR to RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Resize frame for better performance
            height, width = rgb_frame.shape[:2]
            if width > 640:
                scale = 640 / width
                new_width = 640
                new_height = int(height * scale)
                rgb_frame = cv2.resize(rgb_frame, (new_width, new_height))
            
            # Get pose predictions
            predictions, _, _ = self.predictor.numpy_image(rgb_frame)
            
            # Find the best person (highest confidence)
            best_person = None
            best_score = -1.0
            
            for ann in predictions:
                if not hasattr(ann, 'data'):
                    continue
                keypoints = ann.data
                if keypoints is None or len(keypoints) == 0:
                    continue
                
                # Calculate score based on number of visible keypoints
                score = float((keypoints[:, 2] > 0.1).sum())
                if score > best_score:
                    best_score = score
                    best_person = keypoints
            
            # Analyze pose for fall detection
            is_fall = False
            confidence = 0.0
            angle = 0.0
            
            if best_person is not None:
                is_fall, confidence, angle = self._analyze_pose(best_person)
            
            # Update consecutive fall counter
            if is_fall:
                self.consec_fall_like += 1
            else:
                self.consec_fall_like = max(0, self.consec_fall_like - 1)
            
            # Final decision based on consecutive frames
            final_fall = self.consec_fall_like >= self.confirm_frames
            
            # Update result
            result = {
                'is_fall': final_fall,
                'confidence': confidence,
                'angle': angle,
                'timestamp': time.time(),
                'consecutive_frames': self.consec_fall_like,
                'keypoints_detected': best_score
            }
            
            self.last_result = result
            return result
            
        except Exception as e:
            logging.error(f"Error processing frame: {e}")
            return {
                'is_fall': False,
                'confidence': 0.0,
                'angle': 0.0,
                'timestamp': time.time(),
                'error': str(e)
            }
    
    def _analyze_pose(self, keypoints: np.ndarray) -> tuple:
        """
        Analyze pose keypoints to detect fall.
        
        Args:
            keypoints: Array of keypoints with shape (17, 3) [x, y, confidence]
            
        Returns:
            Tuple of (is_fall, confidence, angle)
        """
        try:
            # Check if we have enough valid keypoints
            valid = keypoints[:, 2] > 0.1
            if valid.sum() < 5:
                return False, 0.0, 0.0
            
            # Calculate bounding box aspect ratio
            xs = keypoints[valid, 0]
            ys = keypoints[valid, 1]
            w = (xs.max() - xs.min()) + 1e-6
            h = (ys.max() - ys.min()) + 1e-6
            aspect = h / w  # small aspect ratio = lying down
            
            # Check for required keypoints (shoulders and hips)
            needed = [5, 6, 11, 12]  # left shoulder, right shoulder, left hip, right hip
            if not all(i < len(keypoints) for i in needed):
                return False, 0.0, 0.0
            
            if min(keypoints[5, 2], keypoints[6, 2], keypoints[11, 2], keypoints[12, 2]) <= 0.1:
                return False, 0.0, 0.0
            
            # Calculate torso tilt angle
            shoulder_mid = np.array([
                (keypoints[5, 0] + keypoints[6, 0]) / 2.0,
                (keypoints[5, 1] + keypoints[6, 1]) / 2.0
            ])
            hip_mid = np.array([
                (keypoints[11, 0] + keypoints[12, 0]) / 2.0,
                (keypoints[11, 1] + keypoints[12, 1]) / 2.0
            ])
            
            # Vector from shoulders to hips
            torso_vector = hip_mid - shoulder_mid
            up_vector = np.array([0.0, -1.0])  # Upward direction
            
            # Calculate angle between torso and vertical
            torso_norm = torso_vector / (np.linalg.norm(torso_vector) + 1e-6)
            cos_angle = float(np.clip(np.dot(torso_norm, up_vector), -1.0, 1.0))
            angle_deg = np.degrees(np.arccos(cos_angle))
            
            # Fall detection criteria
            aspect_threshold = 0.75  # Lower aspect ratio = more horizontal
            angle_threshold = 40.0   # Higher angle = more tilted
            
            is_fall = (aspect < aspect_threshold) and (angle_deg > angle_threshold)
            
            # Calculate confidence based on how extreme the values are
            aspect_confidence = min(1.0, (aspect_threshold - aspect) / aspect_threshold)
            angle_confidence = min(1.0, (angle_deg - angle_threshold) / (90.0 - angle_threshold))
            confidence = (aspect_confidence + angle_confidence) / 2.0
            
            return is_fall, confidence, angle_deg
            
        except Exception as e:
            logging.error(f"Error analyzing pose: {e}")
            return False, 0.0, 0.0
    
    def get_last_result(self) -> Dict[str, Any]:
        """Get the last fall detection result."""
        return self.last_result.copy()
    
    def reset_state(self):
        """Reset the fall detection state."""
        self.consec_fall_like = 0
        self.last_result = {
            'is_fall': False,
            'confidence': 0.0,
            'angle': 0.0,
            'timestamp': None
        }

# Global instance for easy access
_human_fall_detector = None

def get_human_fall_detector(disable_cuda: bool = True) -> HumanFallDetectionWrapper:
    """Get or create the global HumanFallDetection wrapper instance."""
    global _human_fall_detector
    if _human_fall_detector is None:
        _human_fall_detector = HumanFallDetectionWrapper(disable_cuda=disable_cuda)
    return _human_fall_detector

def is_human_fall_detection_available() -> bool:
    """Check if HumanFallDetection is available."""
    return HUMAN_FALL_DETECTION_AVAILABLE


