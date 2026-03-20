#!/usr/bin/env python3
"""
Test script to analyze fall detection videos with different frame sampling strategies.
This script tests the PoseNet model on actual fall videos to find the optimal sampling approach.
"""

import os
import sys
import cv2
import time
import numpy as np
from PIL import Image
import json
from datetime import datetime

# Add the fall-detection-main directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

try:
    from fall_prediction import Fall_prediction
    print("✅ Fall_prediction module loaded successfully")
except ImportError as e:
    print(f"❌ Error importing Fall_prediction: {e}")
    sys.exit(1)

def extract_frames_from_video(video_path, max_frames=200):
    """Extract frames from video file"""
    if not os.path.exists(video_path):
        print(f"❌ Video file not found: {video_path}")
        return []
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"❌ Could not open video: {video_path}")
        return []
    
    frames = []
    frame_count = 0
    
    # Get video properties
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    
    print(f"📹 Video: {os.path.basename(video_path)}")
    print(f"   FPS: {fps:.2f}, Total frames: {total_frames}, Duration: {duration:.2f}s")
    
    while cap.isOpened() and frame_count < max_frames:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Resize to standard size
        rgb_frame = cv2.resize(rgb_frame, (640, 480))
        
        # Convert to PIL Image
        pil_image = Image.fromarray(rgb_frame)
        
        frames.append({
            'frame_number': frame_count,
            'timestamp': frame_count / fps if fps > 0 else frame_count,
            'image': pil_image
        })
        
        frame_count += 1
    
    cap.release()
    print(f"   Extracted {len(frames)} frames")
    return frames, fps

def classify_result(result, conf_threshold=0.7):
    """Classify the fall detection result"""
    try:
        # Extract values from result dictionary
        conf = float(result.get('confidence', 0.0))
        angle = float(result.get('angle', 0.0))
        
        # Determine if it's a fall
        is_fall = conf >= conf_threshold
        
        # Create label
        label = 'fall' if is_fall else 'no fall'
        
        return is_fall, label, conf, angle
    except Exception as e:
        print(f"Error classifying result: {e}")
        return False, 'error', 0.0, 0.0

def test_frame_sampling_strategy(frames, fps, strategy_name, frame_interval, window_size=3):
    """Test a specific frame sampling strategy"""
    print(f"\n🔍 Testing strategy: {strategy_name}")
    print(f"   Frame interval: {frame_interval} frames ({frame_interval/fps:.2f}s)")
    print(f"   Window size: {window_size}")
    
    results = []
    fall_detections = 0
    
    # Calculate how many frame groups we can process
    max_start_frame = len(frames) - window_size
    if max_start_frame < 0:
        print("   ❌ Not enough frames for window size")
        return None
    
    # Process frames with the given interval
    for start_frame in range(0, max_start_frame + 1, frame_interval):
        if start_frame + window_size - 1 >= len(frames):
            break
        
        try:
            # Get the frame group
            frame_group = frames[start_frame:start_frame + window_size]
            if len(frame_group) != window_size:
                continue
            
            # Extract PIL images
            img1, img2, img3 = frame_group[0]['image'], frame_group[1]['image'], frame_group[2]['image']
            
            # Process with PoseNet model
            start_time = time.time()
            result = Fall_prediction(img1, img2, img3)
            processing_time = (time.time() - start_time) * 1000
            
            # Classify result
            is_fall, label, conf, angle = classify_result(result)
            
            if is_fall:
                fall_detections += 1
            
            frame_result = {
                'start_frame': start_frame,
                'timestamp': frame_group[0]['timestamp'],
                'is_fall': is_fall,
                'confidence': conf,
                'angle': angle,
                'label': label,
                'processing_time': processing_time
            }
            
            results.append(frame_result)
            
            # Print first few results for debugging
            if len(results) <= 5:
                print(f"   Frame {start_frame}: {label} (conf={conf:.3f}, angle={angle:.1f}°)")
            
        except Exception as e:
            print(f"   ❌ Error processing frame {start_frame}: {e}")
            continue
    
    # Analyze results
    if results:
        best_result = max(results, key=lambda x: x['confidence'])
        avg_confidence = sum(r['confidence'] for r in results) / len(results)
        
        strategy_result = {
            'strategy_name': strategy_name,
            'frame_interval': frame_interval,
            'time_interval': frame_interval / fps,
            'window_size': window_size,
            'total_groups_processed': len(results),
            'fall_detections': fall_detections,
            'fall_detection_rate': fall_detections / len(results) if results else 0,
            'best_confidence': best_result['confidence'],
            'best_angle': best_result['angle'],
            'average_confidence': avg_confidence,
            'overall_fall_detected': fall_detections > 0,
            'results': results
        }
        
        print(f"   📊 Results: {fall_detections}/{len(results)} fall detections")
        print(f"   📊 Best confidence: {best_result['confidence']:.3f}")
        print(f"   📊 Average confidence: {avg_confidence:.3f}")
        print(f"   📊 Overall fall detected: {'✅ YES' if fall_detections > 0 else '❌ NO'}")
        
        return strategy_result
    else:
        print("   ❌ No results generated")
        return None

def test_video(video_path):
    """Test a single video with multiple strategies"""
    print(f"\n{'='*60}")
    print(f"🎬 TESTING VIDEO: {os.path.basename(video_path)}")
    print(f"{'='*60}")
    
    # Extract frames
    frames, fps = extract_frames_from_video(video_path)
    if not frames:
        return None
    
    # Define different sampling strategies to test
    strategies = [
        # Strategy 1: Very short intervals (current approach)
        ("Consecutive Frames", 1, 3),
        ("Every 2 Frames", 2, 3),
        ("Every 3 Frames", 3, 3),
        
        # Strategy 2: Medium intervals (0.1-0.5 seconds)
        ("0.1s Intervals", max(1, int(fps * 0.1)), 3),
        ("0.2s Intervals", max(1, int(fps * 0.2)), 3),
        ("0.5s Intervals", max(1, int(fps * 0.5)), 3),
        
        # Strategy 3: Longer intervals (1-2 seconds)
        ("1.0s Intervals", max(1, int(fps * 1.0)), 3),
        ("1.5s Intervals", max(1, int(fps * 1.5)), 3),
        ("2.0s Intervals", max(1, int(fps * 2.0)), 3),
        
        # Strategy 4: Different window sizes
        ("0.5s Intervals, 5-frame window", max(1, int(fps * 0.5)), 5),
        ("1.0s Intervals, 5-frame window", max(1, int(fps * 1.0)), 5),
    ]
    
    all_results = []
    
    for strategy_name, frame_interval, window_size in strategies:
        result = test_frame_sampling_strategy(frames, fps, strategy_name, frame_interval, window_size)
        if result:
            all_results.append(result)
    
    # Find the best strategy
    if all_results:
        # Sort by fall detection rate, then by best confidence
        best_strategy = max(all_results, key=lambda x: (x['fall_detection_rate'], x['best_confidence']))
        
        print(f"\n🏆 BEST STRATEGY FOR {os.path.basename(video_path)}:")
        print(f"   Strategy: {best_strategy['strategy_name']}")
        print(f"   Frame interval: {best_strategy['frame_interval']} frames ({best_strategy['time_interval']:.2f}s)")
        print(f"   Window size: {best_strategy['window_size']}")
        print(f"   Fall detections: {best_strategy['fall_detections']}/{best_strategy['total_groups_processed']}")
        print(f"   Best confidence: {best_strategy['best_confidence']:.3f}")
        print(f"   Overall fall detected: {'✅ YES' if best_strategy['overall_fall_detected'] else '❌ NO'}")
        
        return {
            'video_name': os.path.basename(video_path),
            'fps': fps,
            'total_frames': len(frames),
            'best_strategy': best_strategy,
            'all_strategies': all_results
        }
    
    return None

def main():
    """Main function to test fall detection videos"""
    print("🚀 Fall Detection Video Analysis Tool")
    print("=" * 50)
    
    # Look for test videos
    video_files = ['output.mp4', 'test1.mp4']
    found_videos = []
    
    # Check current directory
    for video_file in video_files:
        if os.path.exists(video_file):
            found_videos.append(video_file)
    
    # Check parent directory (v3 folder)
    parent_dir = os.path.dirname(current_dir)
    for video_file in video_files:
        video_path = os.path.join(parent_dir, video_file)
        if os.path.exists(video_path):
            found_videos.append(video_path)
    
    if not found_videos:
        print("❌ No test videos found!")
        print("Please ensure 'output.mp4' and 'test1.mp4' are in the current directory or parent directory.")
        return
    
    print(f"📹 Found {len(found_videos)} test video(s): {[os.path.basename(v) for v in found_videos]}")
    
    # Test each video
    all_video_results = []
    for video_path in found_videos:
        result = test_video(video_path)
        if result:
            all_video_results.append(result)
    
    # Summary
    print(f"\n{'='*60}")
    print("📋 SUMMARY")
    print(f"{'='*60}")
    
    for result in all_video_results:
        video_name = result['video_name']
        best_strategy = result['best_strategy']
        print(f"\n🎬 {video_name}:")
        print(f"   Best strategy: {best_strategy['strategy_name']}")
        print(f"   Frame interval: {best_strategy['frame_interval']} frames ({best_strategy['time_interval']:.2f}s)")
        print(f"   Fall detected: {'✅ YES' if best_strategy['overall_fall_detected'] else '❌ NO'}")
        print(f"   Confidence: {best_strategy['best_confidence']:.3f}")
    
    # Save detailed results to JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"fall_detection_analysis_{timestamp}.json"
    
    with open(results_file, 'w') as f:
        json.dump(all_video_results, f, indent=2, default=str)
    
    print(f"\n💾 Detailed results saved to: {results_file}")
    
    # Recommendations
    print(f"\n💡 RECOMMENDATIONS:")
    print("Based on the analysis, update the video processing in app.py with the best strategy:")
    print("1. Use longer frame intervals (0.5-2.0 seconds) instead of consecutive frames")
    print("2. Consider using 5-frame windows for better motion detection")
    print("3. Process fewer frame groups but with better temporal spacing")

if __name__ == "__main__":
    main()
