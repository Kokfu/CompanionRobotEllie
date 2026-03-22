#!/usr/bin/env python3
"""
Quick fall detection test - tests only the optimal strategy found
"""

import os
import sys
import cv2
import time
import warnings
from PIL import Image

# Suppress warnings
warnings.filterwarnings("ignore")
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from fall_prediction import Fall_prediction
    print("✅ Fall_prediction module loaded")
except ImportError as e:
    print(f"❌ Error importing Fall_prediction: {e}")
    sys.exit(1)

def classify_result(result, conf_threshold=0.7):
    """Classify the fall detection result"""
    try:
        conf = float(result.get('confidence', 0.0))
        angle = float(result.get('angle', 0.0))
        is_fall = conf >= conf_threshold
        label = 'fall' if is_fall else 'no fall'
        return is_fall, label, conf, angle
    except Exception as e:
        return False, 'error', 0.0, 0.0

def test_video_quick(video_path):
    """Quick test of a video with optimal strategy"""
    print(f"\n🎬 Testing: {os.path.basename(video_path)}")
    
    if not os.path.exists(video_path):
        print(f"❌ Video not found: {video_path}")
        return None
    
    # Extract frames
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"❌ Could not open video")
        return None
    
    frames = []
    frame_count = 0
    fps = cap.get(cv2.CAP_PROP_FPS)
    
    # Extract first 20 frames for quick test
    while cap.isOpened() and frame_count < 20:
        ret, frame = cap.read()
        if not ret:
            break
        
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame = cv2.resize(rgb_frame, (640, 480))
        pil_image = Image.fromarray(rgb_frame)
        frames.append(pil_image)
        frame_count += 1
    
    cap.release()
    print(f"   Extracted {len(frames)} frames")
    
    if len(frames) < 3:
        print("❌ Not enough frames")
        return None
    
    # Test with optimal strategy: consecutive frames
    fall_detections = 0
    best_confidence = 0
    best_angle = 0
    
    print("   Testing consecutive frames (optimal strategy)...")
    
    for i in range(len(frames) - 2):
        try:
            img1, img2, img3 = frames[i], frames[i+1], frames[i+2]
            result = Fall_prediction(img1, img2, img3)
            is_fall, label, conf, angle = classify_result(result)
            
            if is_fall:
                fall_detections += 1
                print(f"   Frame {i}: {label} (conf={conf:.3f}, angle={angle:.1f}°)")
            
            if conf > best_confidence:
                best_confidence = conf
                best_angle = angle
                
        except Exception as e:
            continue
    
    print(f"   📊 Results: {fall_detections} fall detections")
    print(f"   📊 Best confidence: {best_confidence:.3f}")
    print(f"   📊 Overall fall detected: {'✅ YES' if fall_detections > 0 else '❌ NO'}")
    
    return {
        'video': os.path.basename(video_path),
        'fall_detected': fall_detections > 0,
        'fall_count': fall_detections,
        'best_confidence': best_confidence,
        'best_angle': best_angle
    }

def main():
    """Quick test of fall detection videos"""
    print("🚀 Quick Fall Detection Test")
    print("=" * 40)
    
    # Test videos
    videos = ['output.mp4', 'test1.mp4']
    results = []
    
    for video in videos:
        if os.path.exists(video):
            result = test_video_quick(video)
            if result:
                results.append(result)
        else:
            print(f"⚠️  Video not found: {video}")
    
    # Summary
    print(f"\n📋 SUMMARY:")
    print("=" * 40)
    
    for result in results:
        status = "✅ FALL DETECTED" if result['fall_detected'] else "❌ NO FALL"
        print(f"{result['video']}: {status} (conf={result['best_confidence']:.3f})")
    
    if results:
        total_detected = sum(1 for r in results if r['fall_detected'])
        print(f"\n🎯 Overall: {total_detected}/{len(results)} videos detected falls")
        
        if total_detected == len(results):
            print("🎉 SUCCESS: All fall videos detected correctly!")
        else:
            print("⚠️  Some fall videos not detected - may need adjustment")

if __name__ == "__main__":
    main()

