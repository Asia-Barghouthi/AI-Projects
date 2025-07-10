import streamlit as st
import cv2
import os
import time
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort

# Load YOLO model
model = YOLO('yolov8n.pt')

vehicle_classes = {
    2: 'Car',
    7: 'Truck',
    3: 'Motorcycle',
    1: 'Bicycle',
    80: 'Ambulance'
}

tracker = DeepSort(max_age=30, n_init=3)

entry_line = [(170, 50), (260, 50)]
exit_line = [(300, 50), (450, 50)]

entry_count = 0
exit_count = 0

object_positions = {}
counted_objects = {}
blocking_objects = {}

def process_video(video_file, skip_frames=4):
    global entry_count, exit_count

    temp_video_path = 'temp_video.mp4'
    output_video_path = 'processed_video.mp4'

    with open(temp_video_path, 'wb') as f:
        f.write(video_file.read())

    cap = cv2.VideoCapture(temp_video_path)
    if not cap.isOpened():
        st.error("Error: Could not open video.")
        return None

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))

    video_placeholder = st.empty()

    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_count % skip_frames != 0:
            frame_count += 1
            continue

        frame = cv2.resize(frame, (640, 360))

        results = model(frame)

        detections = []
        for idx, result in enumerate(results):
            for box in result.boxes:
                class_id = int(box.cls.item())
                if class_id in vehicle_classes:
                    xyxy = box.xyxy.tolist()[0]  # [x1, y1, x2, y2] (left, top, right, bottom)
                    confidence = box.conf.item()
                    if confidence > 0.5:  # Set a confidence threshold
                        detections.append(([xyxy[0], xyxy[1], xyxy[2] - xyxy[0], xyxy[3] - xyxy[1]], confidence, class_id))

        tracks = tracker.update_tracks(detections, frame=frame)

        current_time = time.time()

        for track in tracks:
            if not track.is_confirmed():
                continue

            track_id = track.track_id
            class_id = track.det_class
            bbox = track.to_ltrb()

            vehicle_type = vehicle_classes.get(class_id, 'Unknown')

            cv2.rectangle(frame, (int(bbox[0]), int(bbox[1])), (int(bbox[2]), int(bbox[3])), (0, 255, 0), 2)
            label = f"ID: {track_id} - {vehicle_type}"
            cv2.putText(frame, label, (int(bbox[0]), int(bbox[1]) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)

            if track_id not in blocking_objects:
                blocking_objects[track_id] = current_time
            else:
                time_in_frame = current_time - blocking_objects[track_id]
                if time_in_frame > 100:  # Vehicle in frame for more than 5 minutes
                    cv2.putText(frame, "BLOCKING THE WAY", (int(bbox[0]), int(bbox[1]) - 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

            check_line_crossing(track_id, bbox)

        draw_lines(frame)

        # Display entry and exit counts on the video frame
        cv2.putText(frame, f"Entries: {entry_count}", (50, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 1)
        cv2.putText(frame, f"Exits: {exit_count}", (50, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 1)

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_placeholder.image(frame_rgb, channels="RGB", use_column_width=True)

        out.write(cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR))

        frame_count += 1

    cap.release()
    out.release()
    os.remove(temp_video_path)

    st.success("Processing complete! You can download the processed video below:")
    st.video(output_video_path)
    with open(output_video_path, "rb") as f:
        st.download_button("Download Processed Video", f, "processed_video.mp4")

def check_line_crossing(object_id, bbox):
    global entry_count, exit_count

    current_position = [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2]

    if object_id not in object_positions:
        object_positions[object_id] = current_position
        counted_objects[object_id] = {"entry": False, "exit": False}
        return

    previous_position = object_positions[object_id]

    if not counted_objects[object_id]["entry"] and has_crossed_line(previous_position, current_position, entry_line):
        entry_count += 1
        counted_objects[object_id]["entry"] = True

    elif not counted_objects[object_id]["exit"] and has_crossed_line(previous_position, current_position, exit_line):
        exit_count += 1
        counted_objects[object_id]["exit"] = True

    object_positions[object_id] = current_position

def has_crossed_line(prev_pos, curr_pos, line):
    """
    Check if the vehicle has crossed a line based on direction of movement.
    """
    x1, y1 = line[0]
    x2, y2 = line[1]

    # If the line is horizontal (same y-coordinates), check if the vehicle crosses vertically
    if y1 == y2:
        return prev_pos[1] < y1 and curr_pos[1] >= y1  # Crossed from above to below

    return False

def draw_lines(frame):
    cv2.line(frame, entry_line[0], entry_line[1], (255, 0, 0), 2)
    cv2.line(frame, exit_line[0], exit_line[1], (0, 0, 255), 2)

st.title("Vehicle Counting with Line Crossing, Tracking, and Blocking Detection")

uploaded_video = st.file_uploader("Upload a video", type=["mp4", "mov", "avi"])

if uploaded_video is not None:
    st.text("Processing video...")
    process_video(uploaded_video)
