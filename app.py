"""Flask application for RAG Chatbot Evaluation Dashboard."""

import os
import json
import uuid
import time
import asyncio
import threading
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename

from flask_compress import Compress

from config import Config
from evaluator import DataLoader, LLMJudge, DifyClient, ResultsCache, export_to_csv_with_persian_support

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = Config.RESULTS_DIR
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 43200  # 12 hours cache for static assets
app.secret_key = Config.SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

# CSRF protection
csrf = CSRFProtect(app)

# Response compression
Compress(app)

@app.template_filter('stamp')
def format_stamp(value):
    """'20260928_101000' -> '2026-09-28 10:10'; anything else is returned unchanged."""
    try:
        return datetime.strptime(value, '%Y%m%d_%H%M%S').strftime('%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        return value

# Results file cache
results_cache = ResultsCache()

# Ensure results directory exists
os.makedirs(Config.RESULTS_DIR, exist_ok=True)

# Ensure uploads directory exists for data collection
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOADS_DIR, exist_ok=True)

# In-memory storage for background jobs
collection_jobs = {}
evaluation_jobs = {}

# File locks for concurrent write safety
_file_locks = {}
_file_locks_lock = threading.Lock()


def get_file_lock(filename: str) -> threading.Lock:
    """Get or create a threading.Lock for a given filename."""
    with _file_locks_lock:
        if filename not in _file_locks:
            _file_locks[filename] = threading.Lock()
        return _file_locks[filename]


# Cached DataLoaders to avoid re-parsing datasets on every request
_cached_loaders = {}  # {path: (loader, mtime)}
_loader_lock = threading.Lock()

REQUIRED_COLUMNS = {'سوال', 'جواب مرجع', 'Agent Response'}


def get_cached_loader(file_path=None):
    """Return a cached DataLoader, reloading only if the file changed."""
    if file_path is None:
        file_path = Config.DATASET_PATH
    with _loader_lock:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Dataset not found: {file_path}")

        current_mtime = os.path.getmtime(file_path)
        cached = _cached_loaders.get(file_path)
        if cached is None or cached[1] != current_mtime:
            loader = DataLoader(file_path)
            loader.load()
            _cached_loaders[file_path] = (loader, current_mtime)
            return loader
        return cached[0]


def get_available_datasets():
    """Scan uploads dir for valid dataset files with required columns."""
    import pandas as pd
    datasets = []
    for fname in os.listdir(Config.UPLOADS_DIR):
        if not fname.endswith(('.csv', '.xlsx', '.xls')):
            continue
        fpath = os.path.join(Config.UPLOADS_DIR, fname)
        try:
            if fname.endswith('.csv'):
                df = pd.read_csv(fpath, encoding='utf-8-sig', nrows=0)
            else:
                df = pd.read_excel(fpath, nrows=0)
            if not REQUIRED_COLUMNS.issubset(set(df.columns)):
                continue
            # Get full row count
            loader = get_cached_loader(fpath)
            datasets.append({
                'filename': fname,
                'path': fpath,
                'question_count': loader.get_total_count()
            })
        except Exception:
            continue
    datasets.sort(key=lambda d: d['filename'], reverse=True)
    return datasets


def cleanup_old_jobs(jobs_dict: dict, max_age_seconds: int = 3600):
    """Remove completed/error jobs older than max_age_seconds."""
    now = time.time()
    to_remove = [
        job_id for job_id, job in list(jobs_dict.items())
        if job.get('status') in ('completed', 'error')
        and now - job.get('created_at', 0) > max_age_seconds
    ]
    for job_id in to_remove:
        jobs_dict.pop(job_id, None)


# =============================================================================
# Authentication Decorators
# =============================================================================

def login_required(f):
    """Require user to be logged in."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'role' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Require user to be an admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            return render_template('error.html', error='دسترسی غیرمجاز - فقط مدیران مجاز هستند'), 403
        return f(*args, **kwargs)
    return decorated


# =============================================================================
# Authentication Routes
# =============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page."""
    if 'role' in session:
        if session['role'] == 'admin':
            return redirect(url_for('index'))
        else:
            return redirect(url_for('results_list'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == Config.ADMIN_PASSWORD:
            session['role'] = 'admin'
            session.permanent = True
            return redirect(url_for('index'))
        elif password == Config.EXPERT_PASSWORD:
            session['role'] = 'expert'
            session.permanent = True
            return redirect(url_for('results_list'))
        else:
            return render_template('login.html', error='رمز عبور نادرست')
    return render_template('login.html')


@app.route('/logout')
def logout():
    """Logout and clear session."""
    session.clear()
    return redirect(url_for('login'))


# =============================================================================
# Data Collection Routes
# =============================================================================

@app.route('/collect')
@login_required
@admin_required
def collect_page():
    """Render data collection page - Admin only."""
    # Mask API key for security - show only first 8 chars
    masked_key = Config.DIFY_API_KEY[:8] + '...' if len(Config.DIFY_API_KEY) > 8 else '***'
    return render_template('collect.html',
                          dify_api_url=Config.DIFY_API_URL,
                          dify_api_key=masked_key)


@app.route('/collect/upload', methods=['POST'])
@login_required
@admin_required
def collect_upload():
    """Handle Excel file upload for data collection - Admin only."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'error': 'Invalid file format. Use Excel (.xlsx, .xls)'}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOADS_DIR, filename)
    file.save(filepath)

    return jsonify({'success': True, 'filename': filename})


@app.route('/collect/start', methods=['POST'])
@login_required
@admin_required
def collect_start():
    """Start Dify collection in background - Admin only."""
    # Cleanup old jobs
    cleanup_old_jobs(collection_jobs)

    # Use Dify config from environment variables
    api_url = Config.DIFY_API_URL
    api_key = Config.DIFY_API_KEY

    if not api_key or not api_url:
        return jsonify({'error': 'Dify API configuration missing. Please set DIFY_API_URL and DIFY_API_KEY environment variables.'}), 500

    # Handle FormData (multipart/form-data) with file upload
    if 'file' in request.files:
        # New workflow: upload file and start collection in one request
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOADS_DIR, filename)
        file.save(filepath)
    else:
        # Fallback: handle JSON request (for compatibility)
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        filename = data.get('filename')
        filepath = os.path.join(UPLOADS_DIR, secure_filename(filename)) if filename else None

    if not filepath or not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404

    # Read concurrent workers setting from form (UI sends this)
    try:
        concurrent = int(request.form.get('concurrent', Config.COLLECT_MAX_WORKERS))
    except (ValueError, TypeError):
        concurrent = Config.COLLECT_MAX_WORKERS
    concurrent = max(1, min(30, concurrent))

    # Generate unique job ID
    job_id = str(uuid.uuid4())

    # Initialize job status with real-time counters
    collection_jobs[job_id] = {
        'status': 'running',
        'progress': 0,
        'total': 0,
        'collected': 0,
        'success_count': 0,
        'failed_count': 0,
        'error': None,
        'output_file': None,
        'created_at': time.time()
    }

    def run_collection():
        """Background task for async Dify collection."""
        try:
            dify_client = DifyClient(
                api_url, api_key,
                timeout=Config.COLLECT_TIMEOUT,
                rate_limit_delay=Config.COLLECT_RATE_LIMIT_DELAY
            )

            def progress_callback(completed, total, success, failed):
                collection_jobs[job_id]['collected'] = completed
                collection_jobs[job_id]['total'] = total
                collection_jobs[job_id]['success_count'] = success
                collection_jobs[job_id]['failed_count'] = failed
                collection_jobs[job_id]['progress'] = int(completed / total * 100) if total > 0 else 0

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_excel_filename = f'collected_{timestamp}.xlsx'
            output_excel_path = os.path.join(UPLOADS_DIR, output_excel_filename)

            result = asyncio.run(dify_client.collect_responses_async(
                excel_path=filepath,
                output_path=output_excel_path,
                max_workers=concurrent,
                progress_callback=progress_callback,
            ))

            # Export to CSV with Persian support
            output_csv_filename = f'collected_{timestamp}.csv'
            output_csv_path = os.path.join(UPLOADS_DIR, output_csv_filename)
            export_to_csv_with_persian_support(output_excel_path, output_csv_path)

            # Update final job status
            collection_jobs[job_id]['status'] = 'completed'
            collection_jobs[job_id]['output_file'] = output_csv_filename
            collection_jobs[job_id]['success_count'] = result.get('success', 0)
            collection_jobs[job_id]['failed_count'] = result.get('failed', 0)

        except Exception as e:
            collection_jobs[job_id]['status'] = 'error'
            collection_jobs[job_id]['error'] = str(e)

    # Start background thread (daemon so server can shut down cleanly)
    thread = threading.Thread(target=run_collection, daemon=True)
    thread.start()

    return jsonify({'success': True, 'job_id': job_id})


@app.route('/collect/progress/<job_id>')
@login_required
@admin_required
def collect_progress(job_id):
    """Get collection progress as JSON - Admin only."""
    job = collection_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    return jsonify(job)


@app.route('/collect/download/<filename>')
@login_required
@admin_required
def collect_download(filename):
    """Download collected file - Admin only."""
    filepath = os.path.join(UPLOADS_DIR, secure_filename(filename))

    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404

    return send_file(filepath, as_attachment=True, download_name=filename)


def _load_result_file(filepath):
    """Load and cache a JSON result file."""
    cached = results_cache.get(filepath)
    if cached is not None:
        return cached

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    results_cache.set(filepath, data)
    return data


def get_saved_results():
    """Get list of saved evaluation results."""
    results = []
    for filename in os.listdir(Config.RESULTS_DIR):
        if filename.endswith('.json'):
            filepath = os.path.join(Config.RESULTS_DIR, filename)
            try:
                data = _load_result_file(filepath)
                results.append({
                    'filename': filename,
                    'timestamp': data.get('timestamp', 'Unknown'),
                    'total_evaluated': data.get('aggregates', {}).get('total_evaluated', 0),
                    'overall_score': data.get('aggregates', {}).get('overall', {}).get('average', 0)
                })
            except (json.JSONDecodeError, IOError):
                continue
    return sorted(results, key=lambda x: x['timestamp'], reverse=True)


@app.route('/')
@login_required
@admin_required
def index():
    """Dashboard homepage - Admin only."""
    # Get available datasets from uploads
    available_datasets = get_available_datasets()

    # Dataset info from the first available file (or default)
    if available_datasets:
        first = available_datasets[0]
        dataset_info = {
            'loaded': True,
            'total_questions': first['question_count'],
            'path': first['path']
        }
    else:
        try:
            loader = get_cached_loader()
            dataset_info = {
                'loaded': True,
                'total_questions': loader.get_total_count(),
                'path': Config.DATASET_PATH
            }
        except Exception as e:
            dataset_info = {
                'loaded': False,
                'error': str(e)
            }

    # Get saved results
    saved_results = get_saved_results()

    return render_template('index.html',
                           dataset_info=dataset_info,
                           saved_results=saved_results,
                           available_datasets=available_datasets)


@app.route('/upload', methods=['POST'])
@login_required
@admin_required
def upload_dataset():
    """Upload a new dataset file - Admin only."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not file.filename.endswith(('.csv', '.xlsx', '.xls')):
        return jsonify({'error': 'Invalid file format. Use CSV or Excel.'}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(os.path.dirname(Config.DATASET_PATH), filename)
    file.save(filepath)

    return jsonify({'success': True, 'path': filepath})


@app.route('/evaluate', methods=['POST'])
@login_required
@admin_required
def evaluate():
    """Run evaluation on the dataset in background - Admin only."""
    # Cleanup old jobs
    cleanup_old_jobs(evaluation_jobs)

    try:
        # Accept JSON or form data
        if request.is_json:
            data = request.get_json()
            raw_limit = data.get('limit')
            limit = int(raw_limit) if raw_limit is not None else None
            dataset_file = data.get('dataset')
        else:
            limit = request.form.get('limit', type=int)
            dataset_file = request.form.get('dataset')

        # Resolve dataset path
        dataset_path = None
        if dataset_file:
            safe_name = secure_filename(dataset_file)
            candidate = os.path.join(Config.UPLOADS_DIR, safe_name)
            if os.path.exists(candidate):
                dataset_path = candidate

        # Load dataset
        loader = get_cached_loader(dataset_path)

        questions = loader.get_all_questions()
        if limit and limit > 0:
            questions = questions[:limit]

        total = len(questions)

        # Generate unique job ID
        job_id = str(uuid.uuid4())

        # Initialize job status
        evaluation_jobs[job_id] = {
            'status': 'running',
            'progress': 0,
            'total': total,
            'evaluated': 0,
            'error': None,
            'result_filename': None,
            'created_at': time.time()
        }

        # Prepare result filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        result_filename = f'evaluation_{timestamp}.json'
        result_path = os.path.join(Config.RESULTS_DIR, result_filename)

        def run_evaluation():
            """Background task for evaluation."""
            try:
                judge = LLMJudge()

                def save_callback(results_so_far):
                    """Save partial results to disk after each question."""
                    aggregates = judge.calculate_aggregate_scores(results_so_far)
                    result_data = {
                        'timestamp': timestamp,
                        'model': Config.MODEL_ID,
                        'dataset_file': dataset_file or os.path.basename(Config.DATASET_PATH),
                        'total_questions': total,
                        'status': 'in_progress',
                        'aggregates': aggregates,
                        'results': results_so_far
                    }
                    lock = get_file_lock(result_filename)
                    with lock:
                        with open(result_path, 'w', encoding='utf-8') as f:
                            json.dump(result_data, f, ensure_ascii=False, indent=2)
                    results_cache.invalidate(result_path)

                def progress_callback(current, total_q):
                    evaluation_jobs[job_id]['evaluated'] = current
                    evaluation_jobs[job_id]['total'] = total_q
                    evaluation_jobs[job_id]['progress'] = int(current / total_q * 100) if total_q > 0 else 0

                results = judge.evaluate_batch(
                    questions,
                    progress_callback=progress_callback,
                    save_callback=save_callback
                )

                # Final save with complete status
                aggregates = judge.calculate_aggregate_scores(results)
                result_data = {
                    'timestamp': timestamp,
                    'model': Config.MODEL_ID,
                    'dataset_file': dataset_file or os.path.basename(Config.DATASET_PATH),
                    'total_questions': total,
                    'aggregates': aggregates,
                    'results': results
                }
                lock = get_file_lock(result_filename)
                with lock:
                    with open(result_path, 'w', encoding='utf-8') as f:
                        json.dump(result_data, f, ensure_ascii=False, indent=2)
                results_cache.invalidate(result_path)

                evaluation_jobs[job_id]['status'] = 'completed'
                evaluation_jobs[job_id]['result_filename'] = result_filename
                evaluation_jobs[job_id]['progress'] = 100

            except Exception as e:
                evaluation_jobs[job_id]['status'] = 'error'
                evaluation_jobs[job_id]['error'] = str(e)

        # Start background thread (daemon so server can shut down cleanly)
        thread = threading.Thread(target=run_evaluation, daemon=True)
        thread.start()

        return jsonify({'success': True, 'job_id': job_id})

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f"Evaluation failed: {str(e)}"}), 500


@app.route('/evaluate/progress/<job_id>')
@login_required
@admin_required
def evaluate_progress(job_id):
    """Get evaluation progress as JSON - Admin only."""
    job = evaluation_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    return jsonify(job)


@app.route('/results')
@login_required
def results_list():
    """List all evaluation results - Both roles."""
    saved_results = get_saved_results()
    return render_template('results_list.html', results=saved_results)


@app.route('/results/<filename>')
@login_required
def view_results(filename):
    """View a specific evaluation result - Both roles."""
    filepath = os.path.join(Config.RESULTS_DIR, secure_filename(filename))

    if not os.path.exists(filepath):
        return render_template('error.html', error='Result file not found'), 404

    try:
        data = _load_result_file(filepath)

        results = data.get('results', [])
        scored_count = sum(1 for r in results if r.get('human_evaluation'))
        unscored_ids = [r.get('id') for r in results if not r.get('human_evaluation')]
        first_unscored_id = min(unscored_ids) if unscored_ids else None

        return render_template('results.html',
                               data=data,
                               filename=filename,
                               scored_count=scored_count,
                               first_unscored_id=first_unscored_id)
    except (json.JSONDecodeError, IOError) as e:
        return render_template('error.html', error=f'Error loading results: {str(e)}'), 500


@app.route('/results/<filename>/detail/<int:question_id>')
@login_required
def view_detail(filename, question_id):
    """View detail for a single question evaluation - Both roles."""
    filepath = os.path.join(Config.RESULTS_DIR, secure_filename(filename))

    if not os.path.exists(filepath):
        return render_template('error.html', error='Result file not found'), 404

    try:
        data = _load_result_file(filepath)

        # Find the specific result
        result = None
        for r in data.get('results', []):
            if r.get('id') == question_id:
                result = r
                break

        if not result:
            return render_template('error.html', error='Question not found'), 404

        # Get full question data from the dataset used for this evaluation
        ds_file = data.get('dataset_file')
        ds_path = None
        if ds_file:
            candidate = os.path.join(Config.UPLOADS_DIR, ds_file)
            if os.path.exists(candidate):
                ds_path = candidate
        loader = get_cached_loader(ds_path)
        question_data = loader.get_question(question_id)

        # Progress + navigation context for the scoring flow
        results = data.get('results', [])
        total = len(results)
        scored_count = sum(1 for r in results if r.get('human_evaluation'))
        all_ids = sorted(r.get('id') for r in results)
        position = (all_ids.index(question_id) + 1) if question_id in all_ids else question_id + 1
        prev_id = question_id - 1 if question_id - 1 in all_ids else None
        next_id = question_id + 1 if question_id + 1 in all_ids else None
        # Next still-unscored question (wraps around); skips the current one
        unscored = [r.get('id') for r in results
                    if not r.get('human_evaluation') and r.get('id') != question_id]
        ahead = [i for i in unscored if i > question_id]
        next_unscored_id = ahead[0] if ahead else (min(unscored) if unscored else None)

        return render_template('detail.html',
                               result=result,
                               question_data=question_data,
                               filename=filename,
                               total=total,
                               scored_count=scored_count,
                               position=position,
                               prev_id=prev_id,
                               next_id=next_id,
                               next_unscored_id=next_unscored_id)
    except Exception as e:
        return render_template('error.html', error=f'Error: {str(e)}'), 500


@app.route('/results/<filename>/human-eval/<int:question_id>', methods=['POST'])
@login_required
def save_human_eval(filename, question_id):
    """Save human evaluation for a specific question - Both roles."""
    filepath = os.path.join(Config.RESULTS_DIR, secure_filename(filename))

    if not os.path.exists(filepath):
        return jsonify({'error': 'Result file not found'}), 404

    try:
        # Get JSON data from request
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        score = data.get('score')
        comment = data.get('comment', '')

        # Validate score
        if score is None or not isinstance(score, (int, float)) or score < 1 or score > 10:
            return jsonify({'error': 'Score must be between 1 and 10'}), 400

        # Use file lock for thread-safe read-modify-write
        lock = get_file_lock(filename)
        with lock:
            # Load existing results
            with open(filepath, 'r', encoding='utf-8') as f:
                result_data = json.load(f)

            # Find and update the specific result
            found = False
            for r in result_data.get('results', []):
                if r.get('id') == question_id:
                    r['human_evaluation'] = {
                        'score': int(score),
                        'comment': comment,
                        'evaluated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    found = True
                    break

            if not found:
                return jsonify({'error': 'Question not found'}), 404

            # Save updated results
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
            results_cache.invalidate(filepath)

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/export/<filename>')
@login_required
@admin_required
def export_results(filename):
    """Export results as CSV - Admin only."""
    filepath = os.path.join(Config.RESULTS_DIR, secure_filename(filename))

    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Convert to CSV
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(['ID', 'Question', 'Accuracy', 'Completeness', 'Relevance', 'Faithfulness', 'LLM_Explanation', 'Human_Score', 'Human_Comment'])

        # Data rows
        for r in data.get('results', []):
            human_eval = r.get('human_evaluation', {})
            writer.writerow([
                r.get('id', ''),
                r.get('question', ''),
                r.get('accuracy', ''),
                r.get('completeness', ''),
                r.get('relevance', ''),
                r.get('faithfulness', ''),
                r.get('explanation', ''),
                human_eval.get('score', ''),
                human_eval.get('comment', '')
            ])

        output.seek(0)

        # Create response
        csv_filename = filename.replace('.json', '.csv')
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8-sig')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=csv_filename
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/dataset-info')
@login_required
@admin_required
def api_dataset_info():
    """API endpoint for dataset information - Admin only."""
    try:
        dataset_file = request.args.get('file')
        file_path = None
        if dataset_file:
            safe_name = secure_filename(dataset_file)
            candidate = os.path.join(Config.UPLOADS_DIR, safe_name)
            if os.path.exists(candidate):
                file_path = candidate
        loader = get_cached_loader(file_path)
        return jsonify({
            'total_questions': loader.get_total_count(),
            'path': file_path or Config.DATASET_PATH
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', 'false').lower() in ('true', '1', 'yes')
    host = os.getenv('FLASK_HOST', '127.0.0.1')
    port = int(os.getenv('FLASK_PORT', '5000'))

    print("=" * 50)
    print("RAG Chatbot Evaluation Dashboard")
    print("=" * 50)
    print(f"Dataset: {Config.DATASET_PATH}")
    print(f"Model: {Config.MODEL_ID}")
    print("=" * 50)
    print("Roles: Admin (full access) | Expert (view & score)")
    print("=" * 50)
    print(f"Starting server at http://{host}:{port}")
    print("=" * 50)

    app.run(debug=debug, host=host, port=port)
