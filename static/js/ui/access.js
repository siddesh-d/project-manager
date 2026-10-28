// Role-based access and session refresh (split from ui.js)

function normalizeRoleName(role) {
  return String(role || '').trim().replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').toLowerCase();
}

window.applyRoleBasedAccess = function () {
  const currentUser = window.AppState && window.AppState.currentUser ? window.AppState.currentUser : null;
  const normalizedRole = normalizeRoleName(currentUser && currentUser.role);
  const isPlatformAdmin = normalizedRole === 'platform_admin' || normalizedRole === 'admin';
  const isTenantUser = !!(currentUser && currentUser.tenant_id) && !isPlatformAdmin;
  const isTenantAdmin = normalizedRole === 'tenant_admin' || normalizedRole === 'tenant_user_admin';

  const tenantButton = document.getElementById('tenant-registration-button');
  if (tenantButton) {
    tenantButton.style.display = isPlatformAdmin ? '' : 'none';
    tenantButton.disabled = !isPlatformAdmin;
  }

  const coreInput = document.getElementById('core-project-path');
  const coreBrowseButton = document.getElementById('core-project-browse-button');
  const coreSaveButton = document.getElementById('core-project-save-button');
  const coreActions = document.getElementById('core-project-path-actions');
  const canManageCorePath = isPlatformAdmin;

  if (coreInput) {
    coreInput.readOnly = !canManageCorePath;
    coreInput.disabled = !canManageCorePath;
    coreInput.classList.toggle('opacity-60', !canManageCorePath);
    coreInput.title = canManageCorePath ? 'Platform admin can manage the core project path.' : 'Tenant users must use the platform-assigned core project path.';
  }
  if (coreActions) {
    coreActions.hidden = !canManageCorePath;
    coreActions.style.display = canManageCorePath ? '' : 'none';
    coreActions.style.pointerEvents = canManageCorePath ? 'auto' : 'none';
    coreActions.setAttribute('aria-hidden', String(!canManageCorePath));
  }
  if (coreBrowseButton) {
    coreBrowseButton.disabled = !canManageCorePath;
    coreBrowseButton.hidden = !canManageCorePath;
    coreBrowseButton.setAttribute('aria-disabled', String(!canManageCorePath));
    coreBrowseButton.style.pointerEvents = canManageCorePath ? 'auto' : 'none';
    coreBrowseButton.classList.toggle('opacity-50', !canManageCorePath);
    coreBrowseButton.style.display = canManageCorePath ? '' : 'none';
  }
  if (coreSaveButton) {
    coreSaveButton.disabled = !canManageCorePath;
    coreSaveButton.hidden = !canManageCorePath;
    coreSaveButton.setAttribute('aria-disabled', String(!canManageCorePath));
    coreSaveButton.style.pointerEvents = canManageCorePath ? 'auto' : 'none';
    coreSaveButton.classList.toggle('opacity-50', !canManageCorePath);
    coreSaveButton.style.display = canManageCorePath ? '' : 'none';
  }

  const sourceMode = document.getElementById('proj-source-mode');
  if (sourceMode) {
    const hostOption = Array.from(sourceMode.options).find((opt) => opt.value === 'host');
    if (hostOption) {
      hostOption.disabled = isTenantUser;
      hostOption.hidden = isTenantUser;
    }
    if (isTenantUser || isTenantAdmin) {
      sourceMode.value = 'upload';
    }
  }

  const saveMode = document.getElementById('proj-save-mode');
  if (saveMode) {
    const customOption = Array.from(saveMode.options).find((opt) => opt.value === 'custom');
    if (customOption) customOption.disabled = isTenantUser || isTenantAdmin;
    const currentOption = Array.from(saveMode.options).find((opt) => opt.value === 'current');
    if (currentOption) currentOption.disabled = isTenantUser || isTenantAdmin;
    if (isTenantUser || isTenantAdmin) {
      saveMode.value = 'core';
    }
  }

  const addProjectButton = document.getElementById('btn-open-add-project');
  if (addProjectButton) {
    addProjectButton.style.display = (isPlatformAdmin || isTenantAdmin) ? '' : 'none';
    addProjectButton.disabled = !(isPlatformAdmin || isTenantAdmin);
  }

  const projPathRow = document.getElementById('proj-path-row');
  if (projPathRow) {
    const showPathRow = isPlatformAdmin && (sourceMode && sourceMode.value === 'host');
    projPathRow.classList.toggle('hidden', !showPathRow);
    projPathRow.classList.toggle('flex', showPathRow);
  }

  window.onProjectSourceModeChanged?.();
};

window.refreshCurrentUserSession = async function () {
  try {
    const response = await fetch('/api/session', { cache: 'no-store' });
    if (!response.ok) {
      window.AppState = window.AppState || {};
      window.AppState.currentUser = null;
      window.applyRoleBasedAccess();
      return;
    }
    const payload = await response.json();
    window.AppState = window.AppState || {};
    window.AppState.currentUser = payload && payload.user ? payload.user : null;
    window.applyRoleBasedAccess();
    if (window.AppState.currentUser && window.AppState.currentUser.role) {
      const normalized = String(window.AppState.currentUser.role).replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').toLowerCase();
      if (normalized === 'platform_admin' || normalized === 'admin') {
        window.loadTenantDirectory?.();
      }
    }
  } catch (error) {
    window.AppState = window.AppState || {};
    window.AppState.currentUser = null;
    window.applyRoleBasedAccess();
  }
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    window.refreshCurrentUserSession();
  }, { once: true });
} else {
  window.refreshCurrentUserSession();
}

