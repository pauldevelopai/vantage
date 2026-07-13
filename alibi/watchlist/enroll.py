"""
Watchlist Enrollment CLI

Command-line tool to enroll faces into the watchlist.
"""

import argparse
import cv2
from pathlib import Path
from datetime import datetime

from alibi.watchlist.watchlist_store import WatchlistStore, WatchlistEntry
from alibi.watchlist.face_detect import FaceDetector
from alibi.watchlist.face_embed import FaceEmbedder


def enroll_face(
    person_id: str,
    label: str,
    image_path: str,
    source_ref: str = "",
    watchlist_path: str = "alibi/data/watchlist.jsonl"
):
    """
    Enroll a face into the watchlist.
    
    Args:
        person_id: Unique identifier for person
        label: Name/alias for operator reference
        image_path: Path to face image
        source_ref: Reference to source document/case
        watchlist_path: Path to watchlist storage
    """
    print(f"\n🔒 Vantage Watchlist Enrollment")
    print(f"=" * 50)
    print(f"Person ID: {person_id}")
    print(f"Label: {label}")
    print(f"Image: {image_path}")
    print(f"Source: {source_ref or 'Not specified'}")
    print()
    
    # Load image
    image_file = Path(image_path)
    if not image_file.exists():
        print(f"❌ Error: Image file not found: {image_path}")
        return False
    
    image = cv2.imread(str(image_file))
    if image is None:
        print(f"❌ Error: Could not read image: {image_path}")
        return False
    
    print(f"✅ Image loaded: {image.shape[1]}x{image.shape[0]}")
    
    # Detect face
    print("🔍 Detecting face...")
    detector = FaceDetector(confidence_threshold=0.5)
    
    result = detector.detect_and_extract(image, return_largest=True)
    
    if result is None:
        print("❌ Error: No face detected in image")
        print("   Tip: Ensure face is clearly visible and well-lit")
        return False
    
    face_crop, bbox = result
    x, y, w, h = bbox
    print(f"✅ Face detected at ({x}, {y}) size {w}x{h}")
    
    # Generate embedding
    print("🧠 Generating face embedding...")
    embedder = FaceEmbedder()
    
    embedding = embedder.generate_embedding(face_crop)
    print(f"✅ Embedding generated: {len(embedding)}-dimensional vector")
    
    # Create watchlist entry
    entry = WatchlistEntry(
        person_id=person_id,
        label=label,
        embedding=embedding.tolist(),
        added_ts=datetime.utcnow().isoformat(),
        source_ref=source_ref,
        metadata={
            "image_path": str(image_path),
            "face_bbox": {"x": x, "y": y, "w": w, "h": h},
            "image_size": {"width": image.shape[1], "height": image.shape[0]}
        }
    )
    
    # Store in watchlist
    print("💾 Adding to watchlist...")
    store = WatchlistStore(watchlist_path)
    store.add_entry(entry)
    
    total_entries = store.count()
    print(f"✅ Successfully enrolled!")
    print(f"   Watchlist now contains {total_entries} entries")
    print()
    
    return True


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Enroll face into Vantage watchlist",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Enroll from image
  python -m alibi.watchlist.enroll \\
    --person_id SUSPECT_001 \\
    --label "John Doe" \\
    --image /path/to/photo.jpg \\
    --source "Case #2024-1234"
  
  # Enroll with minimal info
  python -m alibi.watchlist.enroll \\
    --person_id SUSPECT_002 \\
    --label "Jane Smith" \\
    --image photo.jpg

Security Note:
  This tool is for authorized law enforcement use only.
  All enrollments are logged with timestamps for audit trail.
        """
    )
    
    parser.add_argument(
        '--person_id',
        required=True,
        help='Unique identifier for person (e.g., SUSPECT_001, CASE_2024_123)'
    )
    
    parser.add_argument(
        '--label',
        required=True,
        help='Name or alias for operator reference'
    )
    
    parser.add_argument(
        '--image',
        required=True,
        help='Path to face image (JPG, PNG)'
    )
    
    parser.add_argument(
        '--source',
        default='',
        help='Source reference (case number, warrant ID, etc.)'
    )
    
    parser.add_argument(
        '--watchlist',
        default='alibi/data/watchlist.jsonl',
        help='Path to watchlist storage file'
    )
    
    args = parser.parse_args()
    
    # Enroll
    success = enroll_face(
        person_id=args.person_id,
        label=args.label,
        image_path=args.image,
        source_ref=args.source,
        watchlist_path=args.watchlist
    )
    
    if success:
        print("✅ Enrollment complete")
        exit(0)
    else:
        print("❌ Enrollment failed")
        exit(1)


if __name__ == "__main__":
    main()
