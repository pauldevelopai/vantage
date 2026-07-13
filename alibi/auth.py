"""
Vantage Authentication & Authorization

JWT-based authentication with role-based access control.
"""

import json
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pathlib import Path
from dataclasses import dataclass
from enum import Enum

import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel


# JWT Configuration
def _get_or_create_secret_key() -> str:
    """Get or create persistent JWT secret key"""
    import os
    
    # Try environment variable first
    secret_key = os.getenv('ALIBI_JWT_SECRET')
    if secret_key:
        return secret_key
    
    # Try persistent file
    secret_file = Path("alibi/data/.jwt_secret")
    if secret_file.exists():
        return secret_file.read_text().strip()
    
    # Generate new secret and persist
    new_secret = secrets.token_urlsafe(32)
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(new_secret)
    
    # Restrict permissions (Unix only)
    try:
        os.chmod(secret_file, 0o600)
    except:
        pass
    
    print("[Auth] ⚠️  Generated new JWT secret key and saved to .jwt_secret")
    print("[Auth] ⚠️  Backup this file! Loss will invalidate all tokens.")
    
    return new_secret

SECRET_KEY = _get_or_create_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours

security = HTTPBearer()


class Role(str, Enum):
    """User roles"""
    OPERATOR = "operator"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"


@dataclass
class User:
    """User account"""
    username: str
    password_hash: str
    role: Role
    full_name: str
    enabled: bool = True
    created_at: Optional[str] = None
    last_login: Optional[str] = None


class UserManager:
    """Manages user accounts"""
    
    def __init__(self, users_file: str = "alibi/data/users.json"):
        self.users_file = Path(users_file)
        self.users: Dict[str, User] = {}
        self.load_users()
    
    def load_users(self):
        """Load users from JSON file"""
        if not self.users_file.exists():
            print(f"[Auth] Creating default users file: {self.users_file}")
            self._create_default_users()
            return
        
        with open(self.users_file, 'r') as f:
            data = json.load(f)
        
        for user_data in data.get('users', []):
            user = User(
                username=user_data['username'],
                password_hash=user_data['password_hash'],
                role=Role(user_data['role']),
                full_name=user_data['full_name'],
                enabled=user_data.get('enabled', True),
                created_at=user_data.get('created_at'),
                last_login=user_data.get('last_login'),
            )
            self.users[user.username] = user
        
        print(f"[Auth] Loaded {len(self.users)} users")
    
    def _create_default_users(self):
        """Create default users with STRONG generated passwords"""
        
        # Generate strong random passwords
        operator_password = secrets.token_urlsafe(16)
        supervisor_password = secrets.token_urlsafe(16)
        admin_password = secrets.token_urlsafe(16)
        
        default_users = [
            {
                "username": "operator1",
                "password": operator_password,
                "role": Role.OPERATOR,
                "full_name": "Operator One",
            },
            {
                "username": "supervisor1",
                "password": supervisor_password,
                "role": Role.SUPERVISOR,
                "full_name": "Supervisor One",
            },
            {
                "username": "admin",
                "password": admin_password,
                "role": Role.ADMIN,
                "full_name": "System Administrator",
            },
        ]
        
        users_data = []
        for user_def in default_users:
            password_hash = self.hash_password(user_def['password'])
            user = User(
                username=user_def['username'],
                password_hash=password_hash,
                role=user_def['role'],
                full_name=user_def['full_name'],
                created_at=datetime.utcnow().isoformat(),
            )
            self.users[user.username] = user
            
            users_data.append({
                "username": user.username,
                "password_hash": user.password_hash,
                "role": user.role.value,
                "full_name": user.full_name,
                "enabled": user.enabled,
                "created_at": user.created_at,
                "last_login": user.last_login,
            })
        
        self.users_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.users_file, 'w') as f:
            json.dump({"users": users_data}, f, indent=2)
        
        # Save passwords to secure file for first-time setup
        passwords_file = self.users_file.parent / ".initial_passwords.txt"
        with open(passwords_file, 'w') as f:
            f.write("=" * 70 + "\n")
            f.write("ALIBI INITIAL PASSWORDS - CHANGE IMMEDIATELY\n")
            f.write("=" * 70 + "\n\n")
            f.write(f"operator1: {operator_password}\n")
            f.write(f"supervisor1: {supervisor_password}\n")
            f.write(f"admin: {admin_password}\n\n")
            f.write("IMPORTANT:\n")
            f.write("1. Change these passwords immediately after first login\n")
            f.write("2. Delete this file after copying passwords\n")
            f.write("3. Store passwords securely (password manager)\n")
            f.write("4. Never share passwords via insecure channels\n")
        
        # Restrict file permissions (Unix only)
        try:
            import os
            os.chmod(passwords_file, 0o600)
        except:
            pass
        
        print()
        print("=" * 70)
        print(f"[Auth] ✅ Created {len(default_users)} users with STRONG generated passwords")
        print("=" * 70)
        print()
        print("🔒 SECURITY NOTICE:")
        print(f"   Initial passwords saved to: {passwords_file}")
        print(f"   ")
        print(f"   operator1:   {operator_password}")
        print(f"   supervisor1: {supervisor_password}")
        print(f"   admin:       {admin_password}")
        print()
        print("⚠️  CRITICAL: ")
        print("   1. Copy these passwords NOW")
        print("   2. Change them immediately after first login")
        print(f"   3. Delete {passwords_file} after copying")
        print("   4. These passwords will NOT be shown again")
        print("=" * 70)
        print()
    
    def save_users(self):
        """Save users to JSON file"""
        users_data = []
        for user in self.users.values():
            users_data.append({
                "username": user.username,
                "password_hash": user.password_hash,
                "role": user.role.value,
                "full_name": user.full_name,
                "enabled": user.enabled,
                "created_at": user.created_at,
                "last_login": user.last_login,
            })
        
        with open(self.users_file, 'w') as f:
            json.dump({"users": users_data}, f, indent=2)
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password using bcrypt"""
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    
    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Verify password against hash"""
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    
    def authenticate(self, username: str, password: str) -> Optional[User]:
        """Authenticate user"""
        user = self.users.get(username)
        
        if not user:
            return None
        
        if not user.enabled:
            return None
        
        if not self.verify_password(password, user.password_hash):
            return None
        
        # Update last login
        user.last_login = datetime.utcnow().isoformat()
        self.save_users()
        
        return user
    
    def get_user(self, username: str) -> Optional[User]:
        """Get user by username"""
        return self.users.get(username)
    
    def create_user(self, username: str, password: str, role: Role, full_name: str) -> User:
        """Create new user"""
        if username in self.users:
            raise ValueError(f"User {username} already exists")
        
        user = User(
            username=username,
            password_hash=self.hash_password(password),
            role=role,
            full_name=full_name,
            created_at=datetime.utcnow().isoformat(),
        )
        
        self.users[username] = user
        self.save_users()
        
        return user
    
    def update_password(self, username: str, new_password: str):
        """Update user password"""
        user = self.users.get(username)
        if not user:
            raise ValueError(f"User {username} not found")
        
        user.password_hash = self.hash_password(new_password)
        self.save_users()
    
    def disable_user(self, username: str):
        """Disable user account"""
        user = self.users.get(username)
        if not user:
            raise ValueError(f"User {username} not found")
        
        user.enabled = False
        self.save_users()


# Global user manager instance
_user_manager: Optional[UserManager] = None


def get_user_manager() -> UserManager:
    """Get global user manager"""
    global _user_manager
    if _user_manager is None:
        _user_manager = UserManager()
    return _user_manager


def create_access_token(username: str, role: str) -> str:
    """Create JWT access token"""
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    payload = {
        "sub": username,
        "role": role,
        "exp": expire,
    }
    
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and verify JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """Get current authenticated user"""
    token = credentials.credentials
    payload = decode_token(token)
    
    username = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    
    user_manager = get_user_manager()
    user = user_manager.get_user(username)
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    if not user.enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled",
        )
    
    return user


async def get_current_user_from_token_query(token: Optional[str] = None) -> User:
    """
    Get current user from query parameter token.
    Used for SSE endpoints where EventSource cannot send custom headers.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token required in query parameter",
        )
    
    payload = decode_token(token)
    
    username = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    
    user_manager = get_user_manager()
    user = user_manager.get_user(username)
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    if not user.enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled",
        )
    
    return user


def require_role(required_roles: List[Role]):
    """Dependency to require specific role(s)"""
    async def role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {[r.value for r in required_roles]}",
            )
        return user
    
    return role_checker


# Pydantic models for API

class LoginRequest(BaseModel):
    """Login request"""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response"""
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    full_name: str


class UserInfo(BaseModel):
    """User information (without sensitive data)"""
    username: str
    role: str
    full_name: str
    enabled: bool
    created_at: Optional[str]
    last_login: Optional[str]


class CreateUserRequest(BaseModel):
    """Create user request"""
    username: str
    password: str
    role: str
    full_name: str


class ChangePasswordRequest(BaseModel):
    """Change password request"""
    old_password: str
    new_password: str
