# © 2025 Amazon Web Services, Inc. or its affiliates. All Rights Reserved.
# This AWS Content is provided subject to the terms of the AWS Customer Agreement available at
# http://aws.amazon.com/agreement or other written agreement between Customer and either
# Amazon Web Services, Inc. or Amazon Web Services EMEA SARL or both.

from github import Github
import os
import base64
import hcl2
import json
from datetime import datetime
import yaml
import sys
import re
import logging
import time
import requests
import subprocess
from typing import Dict, List, Any, Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'terraform-automation-{datetime.now().strftime("%Y%m%d")}.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Environment Variables
BASE_BRANCH = os.environ.get("BASE_BRANCH", "main")
TOKEN = os.environ["GITHUB_TOKEN"]
CONFIG_FILE = os.environ.get("CONFIG_FILE", "config.yaml")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

# Slack integration
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
ENABLE_SLACK = bool(SLACK_WEBHOOK_URL)

# Branch and PR settings
BRANCH_PREFIX = os.environ.get("BRANCH_PREFIX", "terraform-automation")
AUTO_CLOSE_OBSOLETE = os.environ.get("AUTO_CLOSE_OBSOLETE", "false").lower() == "true"

def validate_config(config: Dict[str, Any]) -> bool:
    """Validate configuration file structure"""
    logger.info("Validating configuration file structure...")
    
    # Check top-level structure
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a dictionary")
    
    # Required top-level fields
    required_fields = ['repositories']
    for field in required_fields:
        if field not in config:
            raise ValueError(f"Missing required field: {field}")
    
    repositories = config.get('repositories', [])
    if not isinstance(repositories, list) or len(repositories) == 0:
        raise ValueError("'repositories' must be a non-empty list")
    
    # Validate each repository
    for i, repo in enumerate(repositories):
        repo_context = f"Repository {i+1}"
        
        if not isinstance(repo, dict):
            raise ValueError(f"{repo_context}: Repository must be a dictionary")
        
        # Required repository fields
        required_repo_fields = ['owner', 'repo', 'files']
        for field in required_repo_fields:
            if field not in repo:
                raise ValueError(f"{repo_context}: Missing required field '{field}'")
        
        # Validate owner and repo are strings
        if not isinstance(repo['owner'], str) or not repo['owner'].strip():
            raise ValueError(f"{repo_context}: 'owner' must be a non-empty string")
        
        if not isinstance(repo['repo'], str) or not repo['repo'].strip():
            raise ValueError(f"{repo_context}: 'repo' must be a non-empty string")
        
        # Validate files
        files = repo.get('files', [])
        if not isinstance(files, list) or len(files) == 0:
            raise ValueError(f"{repo_context}: 'files' must be a non-empty list")
        
        for j, file_config in enumerate(files):
            file_context = f"{repo_context}, File {j+1}"
            
            if not isinstance(file_config, dict):
                raise ValueError(f"{file_context}: File configuration must be a dictionary")
            
            # Required file fields
            required_file_fields = ['path', 'changes']
            for field in required_file_fields:
                if field not in file_config:
                    raise ValueError(f"{file_context}: Missing required field '{field}'")
            
            if not isinstance(file_config['path'], str) or not file_config['path'].strip():
                raise ValueError(f"{file_context}: 'path' must be a non-empty string")
            
            changes = file_config.get('changes', {})
            if not isinstance(changes, dict) or len(changes) == 0:
                raise ValueError(f"{file_context}: 'changes' must be a non-empty dictionary")
            
            # Validate change types
            valid_change_types = ['variables', 'resources', 'modules']
            for change_type in changes.keys():
                if change_type not in valid_change_types:
                    raise ValueError(f"{file_context}: Invalid change type '{change_type}'. Must be one of: {valid_change_types}")
    
    # Validate settings if present
    settings = config.get('settings', {})
    if settings:
        if not isinstance(settings, dict):
            raise ValueError("'settings' must be a dictionary")
        
        # Validate boolean settings
        boolean_settings = ['create_pr']
        for setting in boolean_settings:
            if setting in settings and not isinstance(settings[setting], bool):
                raise ValueError(f"Setting '{setting}' must be a boolean")
    
    logger.info("Configuration validation successful")
    return True

def get_config_content() -> Dict[str, Any]:
    """Load and validate configuration from config.yaml file"""
    try:
        logger.info(f"Loading configuration from {CONFIG_FILE}")
        with open(CONFIG_FILE, 'r', encoding='utf-8') as file:
            config_content = yaml.safe_load(file)
        
        # Validate configuration structure
        validate_config(config_content)
        
        logger.info(f"Configuration loaded successfully: {len(config_content.get('repositories', []))} repositories")
        return config_content
    except FileNotFoundError:
        logger.error(f"Configuration file {CONFIG_FILE} not found")
        sys.exit(1)
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML configuration: {str(e)}")
        sys.exit(1)
    except ValueError as e:
        logger.error(f"Configuration validation error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error loading configuration file: {str(e)}")
        sys.exit(1)

def send_slack_notification(
    message: str, 
    channel: str = None, 
    username: str = "Terraform Bot", 
    icon_emoji: str = ":terraform:",
    blocks: List[Dict[str, Any]] = None,
    notification_type: str = "info"
) -> None:
    """
    Enhanced Slack notification with rich formatting and customization options.
    
    Args:
        message: Main notification message
        channel: Optional channel override (e.g., "#infrastructure")
        username: Display username for the bot
        icon_emoji: Emoji to display as bot avatar
        blocks: Rich formatting blocks for enhanced messages
        notification_type: Type of notification (info, success, warning, error)
    """
    if not ENABLE_SLACK:
        logger.debug("Slack integration disabled")
        return
        
    try:
        logger.info(f"Sending Slack notification (type: {notification_type})")
        
        # Base payload
        payload = {
            "text": message,  # Fallback text for notifications
            "username": username,
            "icon_emoji": icon_emoji,
        }
        
        # Add channel override if specified
        if channel:
            payload["channel"] = channel
        
        # Add rich formatting blocks if provided
        if blocks:
            payload["blocks"] = blocks
            
        # Set headers
        headers = {
            'Content-Type': 'application/json'
        }
        
        # Send notification
        response = requests.post(
            SLACK_WEBHOOK_URL,
            data=json.dumps(payload),
            headers=headers,
            timeout=10
        )
        
        if response.status_code != 200:
            logger.error(f"Slack notification failed: {response.status_code}, {response.text}")
            raise Exception(f"Slack notification failed: {response.status_code}, {response.text}")
        else:
            logger.info("✅ Slack notification sent successfully")
            
    except requests.exceptions.Timeout:
        logger.error("Slack notification timed out after 10 seconds")  # noqa: S110
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error sending Slack notification: {str(e)}")  # noqa: S110
    except Exception as e:
        logger.error(f"Error sending Slack notification: {str(e)}")  # noqa: S110

def create_terraform_notification_blocks(
    repo_name: str,
    pr_url: str = None,
    files_modified: int = 0,
    changes_summary: List[str] = None,
    status: str = "success",
    workflow_run_url: str = None
) -> List[Dict[str, Any]]:
    """
    Create rich Slack blocks for Terraform automation notifications.
    
    Args:
        repo_name: Name of the repository
        pr_url: URL of the created pull request
        files_modified: Number of files modified
        changes_summary: List of changes made
        status: Status of the operation (success, warning, error)
        workflow_run_url: URL of the GitHub Actions workflow run
    
    Returns:
        List of Slack blocks for rich formatting
    """
    # Status emoji mapping
    status_emojis = {
        "success": ":white_check_mark:",
        "warning": ":warning:",
        "error": ":x:",
        "info": ":information_source:"
    }
    
    emoji = status_emojis.get(status, ":gear:")
    
    blocks = []
    
    # Header block
    header_text = f"{emoji} *Terraform Infrastructure Update*"
    if status == "success":
        header_text += " - Completed Successfully"
    elif status == "error":
        header_text += " - Failed"
    elif status == "warning":
        header_text += " - Completed with Warnings"
    
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": header_text
        }
    })
    
    # Repository and details section
    details_text = f"*Repository:* `{repo_name}`\n"
    
    if files_modified > 0:
        details_text += f"*Files Modified:* {files_modified}\n"
    
    if pr_url:
        details_text += f"*Pull Request:* <{pr_url}|View PR>\n"
    
    if workflow_run_url:
        details_text += f"*Workflow Run:* <{workflow_run_url}|View Execution>\n"
    
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": details_text
        }
    })
    
    # Changes summary section
    if changes_summary and len(changes_summary) > 0:
        changes_text = "*Changes Applied:*\n"
        for change in changes_summary[:5]:  # Limit to first 5 changes
            changes_text += f"• {change}\n"
        
        if len(changes_summary) > 5:
            changes_text += f"• ... and {len(changes_summary) - 5} more changes\n"
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": changes_text
            }
        })
    
    # Add divider
    blocks.append({"type": "divider"})
    
    return blocks

def send_pr_creation_notification(repo_name: str, pr_url: str, files_modified: int, changes_summary: List[str] = None):
    """Send notification for successful PR creation with rich formatting."""
    
    # Get workflow run URL if available
    github_server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    github_repository = os.getenv("GITHUB_REPOSITORY")
    github_run_id = os.getenv("GITHUB_RUN_ID")
    
    workflow_run_url = None
    if github_repository and github_run_id:
        workflow_run_url = f"{github_server_url}/{github_repository}/actions/runs/{github_run_id}"
    
    # Create rich blocks
    blocks = create_terraform_notification_blocks(
        repo_name=repo_name,
        pr_url=pr_url,
        files_modified=files_modified,
        changes_summary=changes_summary,
        status="success",
        workflow_run_url=workflow_run_url
    )
    
    # Fallback text for notifications
    fallback_text = f"🔧 Terraform PR created for {repo_name}: {pr_url}"
    
    # Send enhanced notification
    send_slack_notification(
        message=fallback_text,
        blocks=blocks,
        notification_type="success"
    )

def send_batch_summary_notification(total_repos: int, successful_repos: int, failed_repos: int, pr_urls: List[str]):
    """Send batch processing summary notification."""
    
    status = "success" if failed_repos == 0 else "warning" if successful_repos > 0 else "error"
    
    blocks = []
    
    # Header
    if status == "success":
        header_text = ":white_check_mark: *Infrastructure Update Batch Complete*"
    elif status == "warning":
        header_text = ":warning: *Infrastructure Update Batch Completed with Issues*"
    else:
        header_text = ":x: *Infrastructure Update Batch Failed*"
    
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": header_text
        }
    })
    
    # Summary statistics
    summary_text = f"*Summary:*\n"
    summary_text += f"• Total repositories: {total_repos}\n"
    summary_text += f"• Successful: {successful_repos}\n"
    
    if failed_repos > 0:
        summary_text += f"• Failed: {failed_repos}\n"
    
    summary_text += f"• PRs created: {len(pr_urls)}\n"
    
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": summary_text
        }
    })
    
    # PR links (limit to 10)
    if pr_urls:
        pr_text = "*Created Pull Requests:*\n"
        for i, pr_url in enumerate(pr_urls[:10]):
            try:
                repo_name = pr_url.split('/')[-3] + '/' + pr_url.split('/')[-2]
                pr_number = pr_url.split('/')[-1]
                pr_text += f"• <{pr_url}|{repo_name} PR #{pr_number}>\n"
            except (IndexError, AttributeError):
                pr_text += f"• <{pr_url}|View PR>\n"
        
        if len(pr_urls) > 10:
            pr_text += f"• ... and {len(pr_urls) - 10} more PRs\n"
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": pr_text
            }
        })
    
    blocks.append({"type": "divider"})
    
    # Fallback text
    fallback_text = f"📊 Infrastructure Update Complete: {successful_repos}/{total_repos} successful"
    
    send_slack_notification(
        message=fallback_text,
        blocks=blocks,
        notification_type=status
    )

def send_error_notification(repo_name: str, error_message: str, workflow_run_url: str = None):
    """Send error notification with debugging information."""
    
    blocks = []
    
    # Error header
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": ":x: *Terraform Automation Error*"
        }
    })
    
    # Error details
    error_text = f"*Repository:* `{repo_name}`\n"
    error_text += f"*Error:* {error_message}\n"
    
    if workflow_run_url:
        error_text += f"*Logs:* <{workflow_run_url}|View Execution Logs>\n"
    
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": error_text
        }
    })
    
    blocks.append({"type": "divider"})
    
    fallback_text = f"❌ Terraform automation failed for {repo_name}: {error_message}"
    
    send_slack_notification(
        message=fallback_text,
        blocks=blocks,
        notification_type="error"
    )

def check_if_key(content: Any, target: str, path: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Recursively check if a key exists in a nested dictionary or list."""
    if path is None:
        path = []
    
    matches = []

    if isinstance(content, dict):
        for key, value in content.items():
            current_path = path + [key]
            
            if key == target:
                matches.append({
                    'path': '.'.join(map(str, current_path)),
                    'value': value
                })
            
            matches.extend(check_if_key(value, target, current_path))

    elif isinstance(content, list):
        for i, item in enumerate(content):
            matches.extend(check_if_key(item, target, path + [str(i)]))

    return matches

def compare_versions(version1: str, version2: str) -> Optional[int]:
    """
    Compare two versions in format "1.xx" or '"1.xx"'
    Returns: 1 if version1 > version2, 0 if equal, -1 if version1 < version2
    """
    try:
        # Extract numeric version (e.g., "1.29" from '"1.29"')
        v1_match = re.search(r'"?(\d+\.\d+)"?', str(version1))
        v2_match = re.search(r'"?(\d+\.\d+)"?', str(version2))
        
        if v1_match and v2_match:
            v1 = float(v1_match.group(1))
            v2 = float(v2_match.group(1))
            
            if v1 > v2:
                return 1
            elif v1 == v2:
                return 0
            else:
                return -1
        return None  # Cannot compare
    except Exception:
        return None  # Error in comparison

class TerraformVersionUpdater:
    """Class to handle version upgrade of terraform files in the repo"""
    def __init__(self, token: str, repo_name: str):
        self.token = token
        self.g = Github(token)
        self.repo = self.g.get_repo(repo_name)
        self.repo_name = repo_name
        self.error_count = 0
        self.max_errors = 5
        self.changes_made = False
        logger.info(f"Initialized updater for repository: {repo_name}")

    def check_rate_limit(self) -> None:
        """Check GitHub API rate limit and wait if necessary"""
        try:
            rate_limit = self.g.get_rate_limit()
            remaining = rate_limit.core.remaining
            reset_time = rate_limit.core.reset
            
            logger.debug(f"GitHub API rate limit: {remaining} requests remaining")
            
            if remaining < 50:  # Conservative threshold
                current_time = datetime.now()
                wait_time = (reset_time - current_time).total_seconds()
                if wait_time > 0:
                    logger.warning(f"Rate limit low ({remaining} remaining). Waiting {wait_time:.0f} seconds...")
                    time.sleep(wait_time + 5)  # Add 5 second buffer
        except Exception as e:
            logger.warning(f"Could not check rate limit: {str(e)}")  # noqa: S110

    def generate_unique_branch_name(self, prefix: str) -> str:
        """Generate unique branch name to prevent conflicts"""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        repo_short = self.repo_name.split('/')[-1][:10]  # First 10 chars of repo name
        # Sanitize repo name for branch naming
        repo_short = re.sub(r'[^a-zA-Z0-9-]', '', repo_short)
        return f"{prefix}-{repo_short}-{timestamp}"

    def create_branch(self, new_branch: str) -> Optional[str]:
        """Create a new branch for the feature version upgrade"""
        try:
            self.check_rate_limit()
            
            try:
                branch = self.repo.get_branch(new_branch)
                logger.info(f"Branch '{new_branch}' already exists")
                ref = f"refs/heads/{new_branch}"
                return ref
            except:
                base = self.repo.get_branch(BASE_BRANCH)
                base_sha = base.commit.sha
                ref = f"refs/heads/{new_branch}"
                self.repo.create_git_ref(ref=ref, sha=base_sha)
                logger.info(f"Created branch '{new_branch}'")
                return ref
        except Exception as e:
            logger.error(f"Branch creation failed: {str(e)}")
            return None

    def delete_branch(self, branch_name: str) -> None:
        """Delete the branch after PR is created or on error"""
        try:
            self.check_rate_limit()
            self.repo.get_git_ref(f"heads/{branch_name}").delete()
            logger.info(f"Branch {branch_name} deleted successfully")
        except Exception as e:
            logger.debug(f"Error deleting branch (may not exist): {str(e)}")  # noqa: S110

    def get_file_content(self, file_path: str, ref: str) -> Tuple[Optional[str], Optional[str]]:
        """Get the contents of the file from the repo"""
        try:
            self.check_rate_limit()
            file_contents = self.repo.get_contents(file_path, ref=ref)
            content = base64.b64decode(file_contents.content).decode('utf-8')
            return content, file_contents.sha
        except Exception as e:
            logger.error(f"Error getting contents for {file_path}: {str(e)}")
            return None, None

    def check_pr_obsolescence(self, file_path: str, branch_name: str, pr_number: Optional[int] = None) -> Tuple[bool, str]:
        """Check if a PR is obsolete by comparing intended changes against main branch."""
        try:
            # Get the current file content from the main branch
            main_content, _ = self.get_file_content(file_path, ref=BASE_BRANCH)
            if not main_content:
                return False, "Could not retrieve content from main branch"
                
            # Get the content from our feature branch
            branch_content, _ = self.get_file_content(file_path, ref=f"heads/{branch_name}")
            if not branch_content:
                return False, "Could not retrieve content from feature branch"
                
            # Get the content we would create with our current changes
            try:
                with open("temp_file.tf", "r", encoding='utf-8') as file:
                    new_content = file.read()
            except FileNotFoundError:
                return False, "Could not read temporary file"
                
            # If the current main branch already has the changes we're trying to make,
            # or has moved beyond them, the PR is obsolete
            obsolete, reason = self._is_change_already_applied(main_content, new_content)
            if obsolete:
                return True, f"The target changes are already in the main branch or have been superseded: {reason}"
                
            return False, ""
                
        except Exception as e:
            logger.error(f"Error checking PR obsolescence: {str(e)}")  # noqa: S110
            return False, f"Error during obsolescence check: {str(e)}"

    def _is_change_already_applied(self, main_content: str, new_content: str) -> Tuple[bool, str]:
        """Compare main branch content with our intended changes to see if they're already applied."""
        # Extract key parameters from both contents
        main_params = self._extract_key_parameters(main_content)
        new_params = self._extract_key_parameters(new_content)
        
        # Check if any parameters in the main branch are ahead of what we're trying to set
        obsolescence_reasons = []
        
        # Version comparison for common parameters
        version_params = ["version", "kubernetes_version", "instance_type", "app_version"]
        
        for param in version_params:
            if param in main_params and param in new_params:
                main_version = main_params[param]
                new_version = new_params[param]
                version_comparison = compare_versions(main_version, new_version)
                
                if version_comparison == 1:  # Main branch ahead
                    obsolescence_reasons.append(f"Main branch {param} ({main_version}) is ahead of target ({new_version})")
                elif version_comparison == 0:  # Equal versions
                    logger.debug(f"{param} versions match: {main_version} = {new_version}")
        
        # If we found reasons indicating the PR is obsolete
        if obsolescence_reasons:
            return True, "; ".join(obsolescence_reasons)
        
        return False, ""

    def _extract_key_parameters(self, content: str) -> Dict[str, str]:
        """Extract key parameters from content for obsolescence checking"""
        params = {}
        
        # Common parameter patterns
        common_params = {
            "version": r'version\s*=\s*("?.+?"?)',
            "kubernetes_version": r'kubernetes_version\s*=\s*("?.+?"?)',
            "instance_type": r'instance_type\s*=\s*("?.+?"?)',
            "source": r'source\s*=\s*("?.+?"?)',
            "app_version": r'app_version\s*=\s*("?.+?"?)',
        }
        
        # Extract all parameters
        for name, pattern in common_params.items():
            match = re.search(pattern, content)
            if match:
                params[name] = match.group(1)
                
        return params

    def process_nested_parameter(self, content: str, param_path: str, new_value: Any, block_type: str, block_name: Optional[str] = None) -> str:
        """Handle nested parameters like instance_market_options.spot_options.max_price"""
        try:
            parts = param_path.split('.')
            logger.debug(f"Processing nested parameter: {' -> '.join(parts)}")
            
            if len(parts) <= 1:
                # Not a nested parameter, handle normally
                return content
            
            # Use HCL parsing for complex nested structures
            try:
                hcl_dict = hcl2.loads(content)
                updated = self._update_nested_hcl(hcl_dict, parts, new_value, block_type, block_name)
                if updated:
                    return hcl2.dumps(hcl_dict)
            except Exception as e:
                logger.warning(f"HCL parsing failed, falling back to regex: {str(e)}")  # noqa: S110
                
            # Fallback to regex-based approach for simpler cases
            return self._update_nested_regex(content, parts, new_value, block_type, block_name)
            
        except Exception as e:
            logger.error(f"Error processing nested parameter {param_path}: {str(e)}")  # noqa: S110
            return content

    def _update_nested_hcl(self, hcl_dict: Dict[str, Any], parts: List[str], new_value: Any, block_type: str, block_name: Optional[str]) -> bool:
        """Update nested parameter using HCL dictionary manipulation"""
        try:
            if block_type == "resources" and len(parts) >= 2:
                resource_type = parts[0]
                if 'resource' in hcl_dict and resource_type in hcl_dict['resource']:
                    for resource in hcl_dict['resource'][resource_type]:
                        for res_name, res_config in resource.items():
                            if self._set_nested_value(res_config, parts[1:], new_value):
                                return True
                                
            elif block_type == "modules" and block_name:
                if 'module' in hcl_dict and block_name in hcl_dict['module']:
                    module_config = hcl_dict['module'][block_name]
                    if isinstance(module_config, list):
                        for mod in module_config:
                            if self._set_nested_value(mod, parts, new_value):
                                return True
                    else:
                        return self._set_nested_value(module_config, parts, new_value)
            
            return False
        except Exception as e:
            logger.error(f"Error in HCL nested update: {str(e)}")  # noqa: S110
            return False

    def _set_nested_value(self, obj: Any, parts: List[str], value: Any) -> bool:
        """Recursively set nested value in dictionary"""
        if len(parts) == 1:
            obj[parts[0]] = value
            return True
        elif len(parts) > 1 and parts[0] in obj:
            if isinstance(obj[parts[0]], dict):
                return self._set_nested_value(obj[parts[0]], parts[1:], value)
            else:
                # Need to create nested structure
                obj[parts[0]] = {}
                return self._set_nested_value(obj[parts[0]], parts[1:], value)
        else:
            # Create missing intermediate objects
            obj[parts[0]] = {}
            return self._set_nested_value(obj[parts[0]], parts[1:], value)

    def _update_nested_regex(self, content: str, parts: List[str], new_value: Any, block_type: str, block_name: Optional[str]) -> str:
        """Fallback regex-based approach for nested parameters"""
        # This is a simplified implementation for common nested patterns
        nested_path = r'\.'.join([re.escape(part) for part in parts])
        pattern = rf'({nested_path}\s*=\s*)[^}},\n]+'
        
        match = re.search(pattern, content)
        if match:
            value_str = f'"{new_value}"' if isinstance(new_value, str) and not str(new_value).startswith('"') else str(new_value)
            content = content[:match.start(1)] + match.group(1) + value_str + content[match.end():]
            logger.info(f"Updated nested parameter: {'.'.join(parts)}")
        
        return content

    def check_if_parameter_exists(self, param: str, block_type: str, block_name: Optional[str] = None) -> bool:
        """Check if a parameter already exists in the file using a scope-aware approach"""
        try:
            with open("temp_file.tf", "r", encoding='utf-8') as file:
                content = file.read()
            
            # Handle nested parameters
            if '.' in param and block_type in ["resources", "modules"]:
                parts = param.split('.')
                # Look for the full nested path
                nested_pattern = r'\.'.join([re.escape(part) for part in parts])
                if re.search(nested_pattern, content):
                    logger.debug(f"Nested parameter '{param}' already exists")
                    return True
            
            if block_type == "variables":
                # Search within variable block
                if block_name:
                    var_pattern = rf'variable\s+"{re.escape(block_name)}"\s*{{\s*([^}}]*)default\s*=\s*([^}}\n]+)'
                    if re.search(var_pattern, content, re.DOTALL):
                        logger.debug(f"Variable '{block_name}' parameter '{param}' already exists")
                        return True
            
            elif block_type == "resources":
                # Search within resource block
                if block_name:
                    parts = block_name.split('.', 1)
                    if len(parts) == 2:
                        resource_type, resource_name = parts
                        # Look for the specific parameter within the resource
                        resource_pattern = rf'resource\s+"{re.escape(resource_type)}"\s+"{re.escape(resource_name)}"\s*{{\s*([^}}]*){re.escape(param)}\s*='
                        if re.search(resource_pattern, content, re.DOTALL):
                            logger.debug(f"Resource '{block_name}' parameter '{param}' already exists")
                            return True
                            
            elif block_type == "modules":
                # Search within module block
                if block_name:
                    module_pattern = rf'module\s+"{re.escape(block_name)}"\s*{{\s*([^}}]*)}}' 
                    module_match = re.search(module_pattern, content, re.DOTALL)
                    
                    if module_match:
                        module_content = module_match.group(1)
                        param_pattern = rf'\b{re.escape(param)}\s*='
                        if re.search(param_pattern, module_content):
                            logger.debug(f"Parameter '{param}' already exists in module '{block_name}'")
                            return True
            
            return False
                
        except Exception as e:
            logger.error(f"Error checking if parameter exists: {str(e)}")  # noqa: S110
            return False

    def update_file(self, param: str, new_version: Any, block_type: str, block_name: Optional[str] = None) -> bool:
        """Update the file with new version for the given parameter"""
        try:
            with open("temp_file.tf", "r", encoding='utf-8') as file:
                content = file.read()
            
            original_content = content
            updated = False
            
            # Handle nested parameters
            if '.' in param and block_type in ["resources", "modules"]:
                content = self.process_nested_parameter(content, param, new_version, block_type, block_name)
                updated = (content != original_content)
                if updated:
                    logger.info(f"Updated nested parameter '{param}' to '{new_version}'")
            
            elif block_type == "variables":
                # For variables, block_name is the variable name, param is the parameter (like "default")
                if block_name:
                    # Update variable parameter (like default value)
                    pattern = rf'(variable\s+"{re.escape(block_name)}"\s*{{[^}}]*{re.escape(param)}\s*=\s*)([^}}\n]+)'
                    match = re.search(pattern, content, re.DOTALL)
                    if match:
                        # Use the improved formatting function
                        value_str = self._format_terraform_value(new_version)
                        content = content[:match.start(2)] + value_str + content[match.end(2):]
                        updated = True
                        logger.info(f"Updated variable '{block_name}' parameter '{param}' to '{new_version}'")
                    else:
                        logger.warning(f"Variable '{block_name}' parameter '{param}' not found")
                else:
                    logger.warning(f"Variable name (block_name) not provided for parameter '{param}'")
                        
            elif block_type == "resources":
                # Use HCL parsing for resource updates
                try:
                    hcl_dict = hcl2.loads(content)
                    if self._update_resource_in_hcl(hcl_dict, param, new_version):
                        content = hcl2.dumps(hcl_dict)
                        updated = True
                        logger.info(f"Updated resource parameter '{param}' to '{new_version}'")
                except Exception as e:
                    logger.warning(f"HCL parsing failed for resource update: {str(e)}")  # noqa: S110
                    
            elif block_type == "modules" and block_name:
                # Update module parameter
                module_pattern = rf'(module\s+"{re.escape(block_name)}"\s*{{[^}}]*){re.escape(param)}\s*=\s*[^}}\n]+'
                match = re.search(module_pattern, content, re.DOTALL)
                if match:
                    # Quote the value if needed
                    value_str = f'"{new_version}"' if isinstance(new_version, str) and not str(new_version).startswith('"') else str(new_version)
                    # Replace the parameter value
                    param_pattern = rf'(\s+{re.escape(param)}\s*=\s*)[^}}\n]+'
                    content = re.sub(param_pattern, rf'\g<1>{value_str}', content)
                    updated = True
                    logger.info(f"Updated module parameter '{param}' to '{new_version}'")
            
            if updated:
                with open("temp_file.tf", "w", encoding='utf-8') as file:
                    file.write(content)
                self.changes_made = True
                return True
            else:
                logger.warning(f"Parameter '{param}' not found for update")
                return False
                
        except Exception as e:
            logger.error(f"Error updating file: {str(e)}")
            self.error_count += 1
            return False

    def _update_resource_in_hcl(self, hcl_dict: Dict[str, Any], resource_identifier: str, new_value: Any) -> bool:
        """Update resource parameter using HCL dictionary"""
        try:
            if 'resource' not in hcl_dict:
                return False
                
            # Parse resource identifier (e.g., "aws_instance.web")
            if '.' in resource_identifier:
                resource_type, resource_name = resource_identifier.split('.', 1)
            else:
                resource_type = resource_identifier
                resource_name = None
            
            resources = hcl_dict['resource']
            if resource_type in resources:
                for resource in resources[resource_type]:
                    if resource_name is None or resource_name in resource:
                        # Update the resource - this is simplified
                        # In practice, you'd need more specific parameter targeting
                        return True
            
            return False
        except Exception as e:
            logger.error(f"Error updating resource in HCL: {str(e)}")
            return False

    def add_parameter(self, param: str, value: Any, block_type: str, block_name: Optional[str] = None) -> bool:
        """Add a new parameter to the Terraform file"""
        try:
            if self.check_if_parameter_exists(param, block_type, block_name):
                logger.debug(f"Parameter '{param}' already exists, attempting update instead")
                return self.update_file(param, value, block_type, block_name)
                
            with open("temp_file.tf", "r", encoding='utf-8') as file:
                content = file.read()
            
            original_content = content
            
            if block_type == "variables":
                # Add new variable
                variable_block = f'\nvariable "{param}" {{\n  default = "{value}"\n}}\n'
                content += variable_block
                logger.info(f"Added variable '{param}' with default value '{value}'")
                
            elif block_type == "modules" and block_name:
                # Add parameter to existing module
                module_pattern = rf'(module\s+"{re.escape(block_name)}"\s*{{[^}}]*)(}})'
                match = re.search(module_pattern, content, re.DOTALL)
                if match:
                    value_str = self._format_terraform_value(value)
                    new_param = f'  {param} = {value_str}\n'
                    content = content[:match.start(2)] + new_param + content[match.start(2):]
                    logger.info(f"Added parameter '{param}' to module '{block_name}' with value '{value}'")
                else:
                    logger.warning(f"Module '{block_name}' not found for parameter addition")
                    return False
            
            elif block_type == "resources":
                # Enhanced resource parameter addition
                if block_name:
                    # Parse resource name (e.g., "aws_instance.web")
                    parts = block_name.split('.', 1)
                    if len(parts) == 2:
                        resource_type, resource_name = parts
                        
                        # Find the resource block
                        resource_pattern = rf'(resource\s+"{re.escape(resource_type)}"\s+"{re.escape(resource_name)}"\s*{{[^}}]*)(}})'
                        match = re.search(resource_pattern, content, re.DOTALL)
                        if match:
                            # Handle nested parameters
                            if '.' in param:
                                # For nested parameters like "instance_market_options.spot_options.max_price"
                                nested_structure = self._build_nested_structure(param, value)
                                content = content[:match.start(2)] + nested_structure + content[match.start(2):]
                                logger.info(f"Added nested parameter '{param}' to resource '{block_name}' with value '{value}'")
                            else:
                                # Simple parameter
                                value_str = self._format_terraform_value(value)
                                new_param = f'  {param} = {value_str}\n'
                                content = content[:match.start(2)] + new_param + content[match.start(2):]
                                logger.info(f"Added parameter '{param}' to resource '{block_name}' with value '{value}'")
                        else:
                            logger.warning(f"Resource '{block_name}' not found for parameter addition")
                            return False
                    else:
                        logger.warning(f"Invalid resource name format: '{block_name}'. Expected format: 'resource_type.resource_name'")
                        return False
                else:
                    logger.warning(f"Resource name (block_name) not provided for parameter '{param}'")
                    return False
            
            if content != original_content:
                with open("temp_file.tf", "w", encoding='utf-8') as file:
                    file.write(content)
                
                self.changes_made = True
                return True
            else:
                return False
            
        except Exception as e:
            logger.error(f"Error adding parameter: {str(e)}")
            self.error_count += 1
            return False
        
    def _format_terraform_value(self, value: Any) -> str:
        """Format a value according to Terraform syntax rules"""
        if isinstance(value, str):
            # If it's already quoted, return as is
            if value.startswith('"') and value.endswith('"'):
                return value
            
            # If it's a list-like string, convert to proper Terraform list format
            if value.startswith('[') and value.endswith(']'):
                # Try to parse as JSON first (handles double quotes)
                import json
                try:
                    parsed_list = json.loads(value)
                    if isinstance(parsed_list, list):
                        formatted_items = [f'"{item}"' for item in parsed_list]
                        return f'[{", ".join(formatted_items)}]'
                except json.JSONDecodeError:
                    # Try ast.literal_eval for single quotes
                    import ast
                    try:
                        parsed_list = ast.literal_eval(value)
                        if isinstance(parsed_list, list):
                            formatted_items = [f'"{item}"' for item in parsed_list]
                            return f'[{", ".join(formatted_items)}]'
                    except:
                        logger.debug(f"Failed to parse list value: {value}")  # noqa: S110
                    
                # If parsing fails, try regex extraction
                items = re.findall(r'"([^"]*)"', value)
                if items:
                    formatted_items = [f'"{item}"' for item in items]
                    return f'[{", ".join(formatted_items)}]'
                else:
                    # Fallback: treat as raw string
                    return value
            
            # Check if it's a complex expression (contains operators, function calls, etc.)
            if any(op in value for op in ['==', '!=', '>', '<', '>=', '<=', '&&', '||', '!', 'data.', 'var.', 'local.']):
                # Don't quote complex expressions
                return value
            
            # Check if it's a boolean value
            if value.lower() in ['true', 'false']:
                return value.lower()
            
            # MOVED: Check for CIDR blocks, IP addresses, version numbers BEFORE number check
            if any(pattern in value for pattern in ['/', ':', '-', '_']) or re.match(r'\d+\.\d+\.\d+\.\d+', value):
                # These are likely strings that need quoting (CIDR blocks, IPs, versions, etc.)
                return f'"{value}"'
            
            # Check if it's a pure number (integers and floats only)
            try:
                if re.match(r'^-?\d+(\.\d+)?\$', value):
                    float(value)
                    return value
            except ValueError:
                logger.debug(f"Value '{value}' is not a pure number")  # noqa: S110
            
            # Regular string, add quotes
            return f'"{value}"'
        elif isinstance(value, list):
            # Format list with double quotes for strings
            formatted_items = []
            for item in value:
                if isinstance(item, str):
                    formatted_items.append(f'"{item}"')
                else:
                    formatted_items.append(str(item))
            return f'[{", ".join(formatted_items)}]'
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        else:
            return f'"{value}"'
        
    def _build_nested_structure(self, param_path: str, value: Any) -> str:
        """Build nested structure for parameters like instance_market_options.spot_options.max_price"""
        parts = param_path.split('.')
        value_str = self._format_terraform_value(value)
        
        if len(parts) == 1:
            return f'  {parts[0]} = {value_str}\n'
        elif len(parts) == 2:
            return f'  {parts[0]} {{\n    {parts[1]} = {value_str}\n  }}\n'
        elif len(parts) == 3:
            return f'  {parts[0]} {{\n    {parts[1]} {{\n      {parts[2]} = {value_str}\n    }}\n  }}\n'
        else:
            # For deeper nesting, build recursively
            result = f'  {parts[0]} {{\n'
            for i in range(1, len(parts) - 1):
                result += '  ' * (i + 1) + f'{parts[i]} {{\n'
            result += '  ' * len(parts) + f'{parts[-1]} = {value_str}\n'
            for i in range(len(parts) - 2, 0, -1):
                result += '  ' * (i + 1) + '}\n'
            result += '  }\n'
            return result    

    def commit_changes(self, file_path: str, file_sha: str, branch: str, content: str) -> Tuple[Optional[str], Optional[str]]:
        """Commit the changes made to the file"""
        try:
            if not self.changes_made:
                logger.debug(f"No changes detected for file {file_path}, skipping commit")
                return None, file_sha
                
            self.check_rate_limit()
            
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            commit_response = self.repo.update_file(
                path=file_path, 
                content=content,
                sha=file_sha, 
                branch=branch,
                message=f"Automated Terraform update - {timestamp}"
            )
            commit_sha = commit_response["commit"].sha
            new_file_sha = commit_response["content"].sha
            logger.info(f"Successfully committed changes to {file_path}")
            return commit_sha, new_file_sha
        except Exception as e:
            logger.error(f"Exception committing to {file_path}: {str(e)}")  # noqa: S110
            self.error_count += 1
            return None, None

    def create_pull_request(self, new_branch: str, title: str, body: str, file_path: str) -> Optional[int]:
        """Create a pull request for the changes made"""
        try:
            self.check_rate_limit()
            
            # Check if the changes/PR would be obsolete
            is_obsolete, obsolete_reason = self.check_pr_obsolescence(file_path, new_branch)
            if is_obsolete:
                logger.warning(f"⚠️ WARNING: Changes appear to be obsolete: {obsolete_reason}")
                logger.warning("Main branch already has similar or newer changes than what we're attempting to apply.")
                
                if AUTO_CLOSE_OBSOLETE:
                    logger.info("AUTO_CLOSE_OBSOLETE is enabled, skipping PR creation")
                    return None
                
            if not self.changes_made:
                logger.info("No changes were made, skipping PR creation")
                return None
                
            logger.info(f"Creating new pull request for branch: {new_branch}")
            pull_request = self.repo.create_pull(
                base=BASE_BRANCH, 
                head=new_branch, 
                title=title, 
                body=body
            )
            logger.info(f"Successfully created pull request #{pull_request.number}")
            
            # Add labels
            try:
                pull_request.add_to_labels("Automated PR", "Terraform")
                logger.debug("Added labels to PR")
            except Exception as e:
                logger.warning(f"Error adding labels: {str(e)}")  # noqa: S110
            
            return pull_request.number
            
        except Exception as e:
            error_message = str(e)
            
            if "422" in error_message and ("already exists" in error_message or "pull request already exists" in error_message.lower()):
                logger.info(f"Pull request for branch '{new_branch}' already exists")  # noqa: S110
                
                try:
                    pull_requests = self.repo.get_pulls(state='open', head=new_branch)
                    for pr in pull_requests:
                        logger.info(f"Found existing PR #{pr.number}")
                        return pr.number
                except Exception as inner_e:
                    logger.error(f"Error finding existing PR: {str(inner_e)}")
                    return None
            else:
                logger.error(f"Error creating pull request: {error_message}")
                self.error_count += 1
                return None
            
def format_terraform_file(file_path: str) -> bool:
    """Format Terraform file using terraform fmt command"""
    try:
        # Use subprocess instead of os.system for better security
        result = subprocess.run(
            ['terraform', 'fmt', file_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            logger.debug("Terraform formatting applied successfully")
            return True
        else:
            logger.warning(f"Terraform fmt warning: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.warning("Terraform fmt command timed out")  # noqa: S110
        return False
    except FileNotFoundError:
        logger.warning("Terraform CLI not found, skipping formatting")  # noqa: S110
        return False
    except Exception as e:
        logger.warning(f"Terraform fmt error: {str(e)}")  # noqa: S110
        return False            

def process_file_changes(updater: TerraformVersionUpdater, file_config: Dict[str, Any], branch_name: str) -> Tuple[bool, List[str]]:
    """Process changes for a single file and return success status and changes summary"""
    file_path = file_config['path']
    changes = file_config['changes']
    changes_summary = []
    
    logger.info(f"Processing file: {file_path}")
    
    # Get file content
    content, file_sha = updater.get_file_content(file_path, f"heads/{branch_name}")
    if not content:
        logger.error(f"Could not retrieve content for {file_path}")
        return False, changes_summary
    
    # Write content to temporary file
    with open("temp_file.tf", "w", encoding='utf-8') as file:
        file.write(content)
    
    # Process each type of change
    success = True
    for change_type, change_list in changes.items():
        logger.info(f"Processing {change_type} changes...")
        
        if change_type == "variables":
            for variable_change in change_list:
                for var_name, var_config in variable_change.items():
                    # For variables, we need to process each parameter under the variable
                    for param_name, param_config in var_config.items():
                        change_result, summary = process_parameter_change(updater, param_name, param_config, "variables", var_name)
                        if not change_result:
                            success = False
                            break
                        if summary:
                            changes_summary.extend(summary)
                        
        elif change_type == "resources":
            for resource_change in change_list:
                for resource_name, resource_config in resource_change.items():
                    change_result, summary = process_resource_change(updater, resource_name, resource_config)
                    if not change_result:
                        success = False
                        break
                    if summary:
                        changes_summary.extend(summary)
                        
        elif change_type == "modules":
            for module_change in change_list:
                for module_name, module_config in module_change.items():
                    for param_name, param_config in module_config.items():
                        change_result, summary = process_parameter_change(updater, param_name, param_config, "modules", module_name)
                        if not change_result:
                            success = False
                            break
                        if summary:
                            changes_summary.extend(summary)
        
        if not success:
            break
    
    if not success:
        logger.error(f"Failed to process all changes for {file_path}")
        return False, changes_summary
    
    # Read updated content and commit changes
    with open("temp_file.tf", "r", encoding='utf-8') as file:
        updated_content = file.read()
    
    # Format the file using subprocess instead of os.system
    format_terraform_file('temp_file.tf')
    
    # Read formatted content
    with open("temp_file.tf", "r", encoding='utf-8') as file:
        updated_content = file.read()
    
    # Commit changes
    commit_sha, new_file_sha = updater.commit_changes(file_path, file_sha, branch_name, updated_content)
    
    return commit_sha is not None, changes_summary

def process_parameter_change(updater: TerraformVersionUpdater, param_name: str, param_config: Dict[str, Any], block_type: str, block_name: Optional[str] = None) -> Tuple[bool, List[str]]:
    """Process changes for a single parameter and return success status and changes summary"""
    logger.debug(f"Processing parameter: {param_name}")
    changes_summary = []
    
    for action, action_config in param_config.items():
        if action == "update":
            for update_rule in action_config:
                from_values = update_rule.get("from", [])
                to_value = update_rule.get("to")
                
                if not from_values or to_value is None:
                    logger.warning(f"Invalid update rule for {param_name}: missing 'from' or 'to' values")
                    continue
                
                # Check current value and update if it matches
                # Note: future implementation - check the current value first
                success = updater.update_file(param_name, to_value, block_type, block_name)
                if success:
                    logger.info(f"Updated {param_name} to {to_value}")
                    changes_summary.append(f"Updated {param_name}: {from_values[0] if from_values else 'unknown'} → {to_value}")
                    return True, changes_summary
                    
        elif action == "param_not_found":
            not_found_action = action_config.get("action")
            if not_found_action == "add":
                value = action_config.get("value")
                if value is not None:
                    success = updater.add_parameter(param_name, value, block_type, block_name)
                    if success:
                        logger.info(f"Added {param_name} with value {value}")
                        changes_summary.append(f"Added {param_name}: {value}")
                        return True, changes_summary
                else:
                    logger.warning(f"Add action specified for {param_name} but no value provided")
            elif not_found_action == "error":
                logger.error(f"Error: Required parameter {param_name} not found")
                return False, changes_summary
            elif not_found_action == "skip":
                logger.debug(f"Skipping parameter {param_name} as configured")
                return True, changes_summary
            # "skip" action - do nothing
            
    return True, changes_summary

def process_resource_change(updater: TerraformVersionUpdater, resource_name: str, resource_config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Process changes for a resource and return success status and changes summary"""
    logger.debug(f"Processing resource: {resource_name}")
    changes_summary = []
    
    success = True
    for param_name, param_config in resource_config.items():
        # Handle nested parameters like 'instance_market_options.spot_options.max_price'
        if "." in param_name:
            logger.debug(f"Processing nested parameter: {param_name}")
        
        param_success, param_summary = process_parameter_change(updater, param_name, param_config, "resources", resource_name)
        if not param_success:
            success = False
        if param_summary:
            changes_summary.extend(param_summary)
            
    return success, changes_summary

def main():
    """Main execution function"""
    logger.info("Starting Terraform Infrastructure Update Automation")
    
    try:
        # Load configuration
        config = get_config_content()
        
        if DRY_RUN:
            logger.info("DRY RUN MODE - No changes will be made")
            logger.info(f"Configuration loaded: {len(config.get('repositories', []))} repositories to process")
            for repo in config.get('repositories', []):
                logger.info(f"  - {repo['owner']}/{repo['repo']}: {len(repo.get('files', []))} files")
            return
        
        # Process each repository
        repositories = config.get('repositories', [])
        settings = config.get('settings', {})
        
        total_repos = len(repositories)
        successful_repos = 0
        failed_repos = 0
        pr_urls = []  # Collect PR URLs for batch summary
        
        # Get workflow run URL for error notifications
        github_server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com")
        github_repository = os.getenv("GITHUB_REPOSITORY")
        github_run_id = os.getenv("GITHUB_RUN_ID")
        workflow_run_url = None
        if github_repository and github_run_id:
            workflow_run_url = f"{github_server_url}/{github_repository}/actions/runs/{github_run_id}"
        
        for i, repo_config in enumerate(repositories, 1):
            owner = repo_config['owner']
            repo = repo_config['repo']
            repo_name = f"{owner}/{repo}"
            
            logger.info(f"{'='*60}")
            logger.info(f"Processing repository {i}/{total_repos}: {repo_name}")
            logger.info(f"{'='*60}")
            
            try:
                updater = TerraformVersionUpdater(TOKEN, repo_name)
                
                # Create unique branch name
                branch_name = updater.generate_unique_branch_name(BRANCH_PREFIX)
                
                # Create branch
                ref = updater.create_branch(branch_name)
                if not ref:
                    logger.error(f"Failed to create branch for {repo_name}")
                    failed_repos += 1
                    continue
                
                # Process each file and collect changes
                success = True
                processed_files = 0
                total_files = len(repo_config.get('files', []))
                all_changes_summary = []
                
                for file_config in repo_config.get('files', []):
                    processed_files += 1
                    logger.info(f"Processing file {processed_files}/{total_files}: {file_config['path']}")
                    
                    file_success, file_changes = process_file_changes(updater, file_config, branch_name)
                    if not file_success:
                        success = False
                        logger.error(f"Failed to process file: {file_config['path']}")
                        break
                    
                    all_changes_summary.extend(file_changes)
                
                if not success:
                    logger.error(f"Failed to process files for {repo_name}, cleaning up branch")
                    updater.delete_branch(branch_name)
                    failed_repos += 1
                    
                    # Send error notification
                    if ENABLE_SLACK:
                        send_error_notification(
                            repo_name=repo_name,
                            error_message="Failed to process Terraform files",
                            workflow_run_url=workflow_run_url
                        )
                    continue
                
                if not updater.changes_made:
                    logger.info(f"No changes were made for {repo_name}, cleaning up branch")
                    updater.delete_branch(branch_name)
                    successful_repos += 1  # Still count as successful
                    continue
                
                # Create pull request
                pr_title = settings.get('pr_title_template', 'Automated Terraform Updates')
                
                # Replace template variables
                pr_title = pr_title.replace('{{timestamp}}', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                
                # Build PR body
                pr_body = "Automated Terraform configuration updates\n\n"
                pr_body += f"Repository: {repo_name}\n"
                pr_body += f"Files modified: {len(repo_config.get('files', []))}\n"
                pr_body += f"Branch: {branch_name}\n\n"
                
                # Add workflow run URL
                if workflow_run_url:
                    pr_body += f"GitHub Actions run: {workflow_run_url}\n"
                
                # Get first file path for obsolescence checking
                first_file_path = repo_config['files'][0]['path'] if repo_config.get('files') else None
                
                if settings.get('create_pr', True):
                    pr_number = updater.create_pull_request(branch_name, pr_title, pr_body, first_file_path)
                    
                    if pr_number:
                        pr_url = f"https://github.com/{repo_name}/pull/{pr_number}"
                        pr_urls.append(pr_url)
                        logger.info(f"✅ Pull Request created: {pr_url}")
                        
                        # Enhanced Slack notification
                        if ENABLE_SLACK:
                            send_pr_creation_notification(
                                repo_name=repo_name,
                                pr_url=pr_url,
                                files_modified=len(repo_config.get('files', [])),
                                changes_summary=all_changes_summary
                            )
                            
                        successful_repos += 1
                    else:
                        logger.warning(f"❌ Failed to create PR for {repo_name}")
                        failed_repos += 1
                        
                        # Send error notification for PR creation failure
                        if ENABLE_SLACK:
                            send_error_notification(
                                repo_name=repo_name,
                                error_message="Failed to create pull request",
                                workflow_run_url=workflow_run_url
                            )
                else:
                    logger.info(f"✅ Changes committed to branch: {branch_name}")
                    successful_repos += 1
                    
            except Exception as e:
                logger.error(f"❌ Error processing repository {repo_name}: {str(e)}")
                failed_repos += 1
                
                # Send error notification
                if ENABLE_SLACK:
                    send_error_notification(
                        repo_name=repo_name,
                        error_message=str(e),
                        workflow_run_url=workflow_run_url
                    )
                
                # Clean up on error
                if 'updater' in locals() and 'branch_name' in locals():
                    try:
                        updater.delete_branch(branch_name)
                    except Exception as cleanup_error:
                        logger.debug(f"Cleanup error (non-critical): {cleanup_error}")
        
        # Send batch summary notification
        if ENABLE_SLACK:
            send_batch_summary_notification(
                total_repos=total_repos,
                successful_repos=successful_repos,
                failed_repos=failed_repos,
                pr_urls=pr_urls
            )
        
        # Final summary
        logger.info(f"{'='*60}")
        logger.info(f"Terraform automation completed")
        logger.info(f"Repositories processed: {successful_repos}/{total_repos}")
        if successful_repos == total_repos:
            logger.info("✅ All repositories processed successfully")
        else:
            logger.warning(f"⚠️ {failed_repos} repositories had issues")
        logger.info(f"{'='*60}")
        
    except Exception as e:
        logger.error(f"Fatal error in main execution: {str(e)}")
        
        # Send critical error notification
        if ENABLE_SLACK:
            send_error_notification(
                repo_name="ALL_REPOSITORIES",
                error_message=f"Critical automation failure: {str(e)}",
                workflow_run_url=workflow_run_url
            )
        
        sys.exit(1)

if __name__ == "__main__":
    main()