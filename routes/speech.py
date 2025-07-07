import os
import time
import tempfile
import glob
from flask import request, jsonify, send_file, Blueprint
from groq import Groq
from utils.user_utils import get_user_id
from functions.chat_functions import generate_ai_response

speech_bp = Blueprint("speech", __name__, url_prefix="/api/speech")

def cleanup_temp_files():
    """
    Clean up old temporary audio files to prevent disk space issues.
    This should be called periodically (e.g., via a background task).
    """
    temp_dir = tempfile.gettempdir()
    pattern = os.path.join(temp_dir, "tmp*.wav")
    current_time = time.time()
    
    for file_path in glob.glob(pattern):
        try:
            # Remove files older than 1 hour
            if current_time - os.path.getctime(file_path) > 3600:
                os.unlink(file_path)
                print(f"Cleaned up old temp file: {file_path}")
        except OSError as e:
            print(f"Failed to clean up {file_path}: {e}")

def transcribe_audio(audio_file):
    """
    Transcribes audio to text using Groq API.
    """
    # API key validation
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable not set")
    
    client = Groq(api_key=api_key)
    
    try:
        # Create a temporary file to save the uploaded audio
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
            audio_file.save(temp_audio.name)
            
            # Transcribe the audio
            with open(temp_audio.name, "rb") as audio_file_obj:
                transcription = client.audio.transcriptions.create(
                    file=audio_file_obj,
                    model="whisper-large-v3"
                )
            
            # Clean up temporary file
            try:
                os.unlink(temp_audio.name)
            except OSError:
                pass
            
            return transcription.text
            
    except Exception as e:
        print(f"[Transcription Error] {e}")
        # Clean up temporary file if it exists
        try:
            if 'temp_audio' in locals():
                os.unlink(temp_audio.name)
        except OSError:
            pass
        raise


def synthesize_text(text, retries=3, delay=1.0):
    """
    Synthesizes text to speech using Groq API with retry logic and proper error handling.
    """
    # Input validation
    if not text or not isinstance(text, str):
        raise TypeError(f"Expected non-empty string for TTS input, got {type(text)}")
    
    # Strip whitespace and check if text is empty after stripping
    text = text.strip()
    if not text:
        raise ValueError("Text input cannot be empty or whitespace only")
    
    # API key validation
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable not set")
    
    client = Groq(api_key=api_key)
    model = "playai-tts"
    voice = "Celeste-PlayAI"
    response_format = "wav"

    for attempt in range(retries):
        try:
            response = client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
                response_format=response_format
            )
            
            # Create temporary file with proper cleanup handling
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
                response.write_to_file(temp_audio.name)
                
                # Verify file was created and has content
                if os.path.exists(temp_audio.name) and os.path.getsize(temp_audio.name) > 0:
                    return temp_audio.name
                else:
                    # Clean up empty file
                    try:
                        os.unlink(temp_audio.name)
                    except OSError:
                        pass
                    raise Exception("Generated audio file is empty or corrupted")

        except Exception as e:
            print(f"[Groq TTS Attempt {attempt+1}/{retries}] Error: {e}")
            
            # Check for specific error types that warrant retry
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in ["no healthy upstream", "503", "timeout", "connection", "rate limit"]):
                if attempt < retries - 1:  # Don't sleep on last attempt
                    sleep_time = delay * (2 ** attempt)  # Exponential backoff
                    print(f"[Groq TTS] Retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
                continue
            else:
                # Non-retryable error, break immediately
                print(f"[Groq TTS] Non-retryable error encountered: {e}")
                break

    print(f"[Groq TTS] All {retries} attempts failed")
    return None


@speech_bp.route('/respond', methods=['POST'])
def respond():
    """
    Enhanced speech response endpoint with comprehensive error handling.
    """
    reply_audio_path = None
    
    try:
        # Authentication validation
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401

        user_id = get_user_id(auth_header)
        if not user_id:
            return jsonify({"error": "Invalid user authentication"}), 401
        
        # Audio file validation
        if 'audio' not in request.files:
            return jsonify({"error": "No audio file provided"}), 400
        
        audio = request.files['audio']
        if audio.filename == '':
            return jsonify({"error": "Empty audio file"}), 400
        
        # Validate audio file size (optional - adjust limit as needed)
        audio.seek(0, 2)  # Seek to end
        file_size = audio.tell()
        audio.seek(0)  # Reset to beginning
        
        if file_size == 0:
            return jsonify({"error": "Audio file is empty"}), 400
        
        # Optional: Set max file size (e.g., 10MB)
        MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
        if file_size > MAX_FILE_SIZE:
            return jsonify({"error": "Audio file too large"}), 413

        # Step 1: Convert speech to text
        try:
            user_text = transcribe_audio(audio)
            if not user_text or not user_text.strip():
                return jsonify({"error": "Could not transcribe audio or audio contains no speech"}), 400
        except Exception as e:
            print(f"[Transcription Error] {e}")
            return jsonify({"error": "Audio transcription failed"}), 500

        # Step 2: Generate AI response
        try:
            aira_reply_obj = generate_ai_response(user_id=user_id, user_input=user_text.strip())
            if not aira_reply_obj:
                return jsonify({"error": "Failed to generate AI response"}), 500
            
            aira_message_text = aira_reply_obj.get("message", "").strip()
            if not aira_message_text:
                return jsonify({"error": "AI response is empty"}), 500
                
        except Exception as e:
            print(f"[AI Response Error] {e}")
            return jsonify({"error": "AI response generation failed"}), 500

        # Step 3: Convert AI response to speech
        try:
            reply_audio_path = synthesize_text(aira_message_text)
            print(f"[AIRA] Generated audio path: {reply_audio_path}")
            
            if not reply_audio_path:
                # Fallback: return text response when TTS fails
                return jsonify({
                    "error": "TTS temporarily unavailable",
                    "aira_text": aira_message_text,
                    "fallback": True
                }), 503
            
            # Verify the audio file exists and is readable
            if not os.path.exists(reply_audio_path):
                return jsonify({
                    "error": "Generated audio file not found",
                    "aira_text": aira_message_text,
                    "fallback": True
                }), 500
                
        except (TypeError, ValueError) as e:
            print(f"[TTS Input Error] {e}")
            return jsonify({
                "error": "Invalid input for text-to-speech",
                "aira_text": aira_message_text,
                "fallback": True
            }), 400
        except Exception as e:
            print(f"[TTS Error] {e}")
            return jsonify({
                "error": "Text-to-speech conversion failed",
                "aira_text": aira_message_text,
                "fallback": True
            }), 500

        # Step 4: Return audio file
        try:
            # Use a custom response that cleans up the file after sending
            def remove_file(response):
                try:
                    if reply_audio_path and os.path.exists(reply_audio_path):
                        os.unlink(reply_audio_path)
                        print(f"[Cleanup] Removed temporary file: {reply_audio_path}")
                except OSError as e:
                    print(f"[Cleanup Error] Failed to remove {reply_audio_path}: {e}")
                return response
            
            response = send_file(
                reply_audio_path,
                mimetype='audio/wav',
                as_attachment=True,
                download_name="aira_reply.wav"
            )
            
            # Register cleanup function to run after response is sent
            response.call_on_close(lambda: remove_file(None))
            cleanup_temp_files()
            return response
            
        except Exception as e:
            print(f"[File Send Error] {e}")
            # Clean up the file if send fails
            if reply_audio_path:
                try:
                    os.unlink(reply_audio_path)
                except OSError:
                    pass
            return jsonify({
                "error": "Failed to send audio file",
                "aira_text": aira_message_text,
                "fallback": True
            }), 500
            
    except Exception as e:
        print(f"[Unexpected Error] {e}")
        # Clean up any temporary files if an unexpected error occurs
        if reply_audio_path:
            try:
                os.unlink(reply_audio_path)
            except OSError:
                pass
        return jsonify({"error": "An unexpected error occurred"}), 500





