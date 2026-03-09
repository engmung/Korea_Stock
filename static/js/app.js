/**
 * Korea_Stock 3D Visualization Logic
 * Frontend built with vanilla Three.js and GSAP for animations.
 */

// Global State
let config = {
    days: 3,
    intervalHours: 12, // 12-hour buckets
    isTimelineMode: false
};

let dataCache = {
    total: {},     // {"Samsung": {"추천": 5, "주의": 1, "관심": 2}}
    timeline: {}   // { 0: {"Samsung": {...}}, 1: {"SK": {...}} }
};

// Three.js Core Variables
let scene, camera, renderer, controls;
let raycaster, mouse;
let elements = []; // Holds references to all mesh objects
let lines = [];    // Holds connecting lines
let hoveredMesh = null;
let selectedStockName = null;
let stockPositions = {}; // Store fixed X,Z coordinates for each stock

// Colors
const COLOR_NEUTRAL = 0x94A3B8;
const COLOR_RECOMMEND = 0xF43F5E;
const COLOR_CAUTION = 0x0EA5E9;
const COLOR_MIXED = 0x8B5CF6; // Purple if mixed

// DOM Elements
const loader = document.getElementById('loader');
const daysInput = document.getElementById('days-input');
const viewToggleBtn = document.getElementById('view-toggle-btn');
const viewText = viewToggleBtn.querySelector('.view-text');
const detailPanel = document.getElementById('detail-panel');
const closePanelBtn = document.getElementById('close-panel-btn');

// Detail Panel Elements
const elTitle = document.getElementById('detail-title');
const elRec = document.getElementById('detail-recommend');
const elCau = document.getElementById('detail-caution');

// Initialization
async function init() {
    initThreeJS();
    setupEventListeners();
    await loadData();
    animate();
}

function showLoader(show) {
    if (show) loader.classList.add('active');
    else loader.classList.remove('active');
}

// ==========================================
// 1. Data Fetching
// ==========================================
async function loadData() {
    showLoader(true);
    try {
        const res = await fetch(`/api/visualization?days=${config.days}&interval_hours=${config.intervalHours}`);
        const result = await res.json();
        
        if (result.status === 'success') {
            dataCache = result.data;
            buildVisualization();
        } else {
            console.error('API Error:', result);
        }
    } catch (e) {
        console.error('Fetch Error:', e);
    } finally {
        showLoader(false);
    }
}

// ==========================================
// 2. Three.js Setup
// ==========================================
function initThreeJS() {
    const container = document.getElementById('canvas-container');

    // Scene
    scene = new THREE.Scene();
    // Add some fog for depth
    scene.fog = new THREE.FogExp2(0x0B0F19, 0.002);

    // Camera
    camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 1, 2000);
    camera.position.set(0, 100, 200);

    // Renderer
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); // optimize performance
    container.appendChild(renderer.domElement);

    // Controls
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.maxPolarAngle = Math.PI / 2 + 0.2; // roughly limit scrolling below ground
    controls.minDistance = 20;
    controls.maxDistance = 500;

    // Grid Helper (Floor)
    const grid = new THREE.GridHelper(400, 40, 0x1e293b, 0x0f172a);
    grid.position.y = -50;
    scene.add(grid);

    // Raycaster for interactions
    raycaster = new THREE.Raycaster();
    mouse = new THREE.Vector2();

    // Window Resize Handler
    window.addEventListener('resize', onWindowResize);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('click', onClick);
}

// ==========================================
// 3. Visualization Builders
// ==========================================
function clearElements() {
    elements.forEach(obj => {
        scene.remove(obj.mesh);
        obj.mesh.geometry.dispose();
        if(Array.isArray(obj.mesh.material)){
            obj.mesh.material.forEach(m=>m.dispose());
        }else{
            obj.mesh.material.dispose();
        }
    });
    elements = [];

    lines.forEach(line => {
        scene.remove(line);
        line.geometry.dispose();
        line.material.dispose();
    });
    lines = [];
}

/** 
 * Calculate color based on recommend/caution ratio
 */
function getColor(rec, cau) {
    if (rec > 0 && cau === 0) return COLOR_RECOMMEND;
    if (cau > 0 && rec === 0) return COLOR_CAUTION;
    if (rec > 0 && cau > 0) return COLOR_MIXED;
    return COLOR_NEUTRAL; // Only '관심'
}

/**
 * Pre-calculate fixed positions for each stock so they align vertically.
 * Arranged in a spiraling distribution.
 */
function calculateStockPositions() {
    stockPositions = {};
    const keys = Object.keys(dataCache.total).sort((a,b) => {
        // Sort by total signals descending
        const totalA = dataCache.total[a]['추천'] + dataCache.total[a]['주의'] + dataCache.total[a]['관심'];
        const totalB = dataCache.total[b]['추천'] + dataCache.total[b]['주의'] + dataCache.total[b]['관심'];
        return totalB - totalA;
    });

    keys.forEach((stockName, idx) => {
        const phi = idx * 1.375; // golden ratio approx
        const rDist = Math.max(15, Math.sqrt(idx) * 22); // Reverted spread to prevent overlap
        stockPositions[stockName] = {
            x: rDist * Math.cos(phi),
            z: rDist * Math.sin(phi)
        };
    });
}

function buildFlatMode() {
    Object.keys(dataCache.total).forEach(stockName => {
        const stats = dataCache.total[stockName];
        const totalSignals = stats['추천'] + stats['주의'] + stats['관심'];
        if (totalSignals === 0) return;
        
        // Base size logic: larger means more total recommendations
        const radius = Math.max(3, Math.min(25, totalSignals * 2.5));
        const color = getColor(stats['추천'], stats['주의']);

        const pos = stockPositions[stockName];
        createDisc(stockName, stats, radius, color, pos.x, 0, pos.z, true);
    });
}

/**
 * 3D Timeline Mode: Data bucketed into 12 hour chunks.
 * Standard Y axis mapping (higher up = more recent).
 */
function buildTimelineMode() {
    const buckets = Object.keys(dataCache.timeline).map(Number).sort((a,b) => a-b);
    if (buckets.length === 0) return;
    
    // Reduces the vertical gap between different dates
    const Y_SPACING = 15;
    
    // Track previous positions for each stock to draw vertical lines
    const prevPos = {};

    buckets.forEach(bucketIdx => {
        const levelData = dataCache.timeline[bucketIdx];
        const yPos = -bucketIdx * Y_SPACING + 50; // newest at +50, older goes downwards
        
        const stocks = Object.keys(levelData);
        
        stocks.forEach((stockName) => {
            const stats = levelData[stockName];
            const totalSignals = stats['추천'] + stats['주의'] + stats['관심'];
            if (totalSignals === 0) return;
            
            const radius = Math.max(2, Math.min(18, totalSignals * 2.5));
            const color = getColor(stats['추천'], stats['주의']);
            
            const pos = stockPositions[stockName];
            
            // Draw disc
            createDisc(stockName, stats, radius, color, pos.x, yPos, pos.z, false);
            
            // Draw connecting line to previous bucket if it exists
            if (prevPos[stockName]) {
                const material = new THREE.LineBasicMaterial({ color: color, transparent: true, opacity: 0.3 });
                const points = [];
                points.push(new THREE.Vector3(pos.x, prevPos[stockName].y, pos.z));
                points.push(new THREE.Vector3(pos.x, yPos, pos.z));
                
                const geometry = new THREE.BufferGeometry().setFromPoints(points);
                const line = new THREE.Line(geometry, material);
                line.userData = { name: stockName };
                scene.add(line);
                lines.push(line);
            }
            
            prevPos[stockName] = { y: yPos };
        });
        
        // Add a subtle ring to delineate the time period visually (around the center)
        const ringGeo = new THREE.RingGeometry(150, 151, 64);
        const ringMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.05, side: THREE.DoubleSide });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.rotation.x = Math.PI / 2;
        ring.position.y = yPos;
        scene.add(ring);
        elements.push({ mesh: ring, isRing: true }); 
    });
}

function createDisc(name, stats, radius, colorHex, tx, ty, tz, isFlatMode) {
    // Cylinder looking like a flat disc (coin)
    const geometry = new THREE.CylinderGeometry(radius, radius, 1, 32);
    
    const material = new THREE.MeshBasicMaterial({
        color: colorHex,
        transparent: true,
        opacity: 0.95
    });

    const mesh = new THREE.Mesh(geometry, material);
    
    // Intro Animation using GSAP
    mesh.position.set(tx, ty + (isFlatMode ? 100 : 50), tz);
    
    mesh.userData = {
        name: name,
        stats: stats,
        baseColor: colorHex,
        targetPos: new THREE.Vector3(tx, ty, tz),
        baseScale: new THREE.Vector3(1, 1, 1)
    };

    scene.add(mesh);
    elements.push({ mesh, data: mesh.userData });

    gsap.to(mesh.position, {
        x: tx, y: ty, z: tz,
        duration: 1.2,
        ease: "power2.out",
        delay: Math.random() * 0.3 
    });
}

function buildVisualization() {
    clearElements();
    calculateStockPositions();

    if (config.isTimelineMode) {
        buildTimelineMode();
        gsap.to(camera.position, { x: 100, y: 30, z: 200, duration: 1.5 });
    } else {
        buildFlatMode();
        gsap.to(camera.position, { x: 0, y: 80, z: 120, duration: 1.5 });
    }
    updateSelectionHighlight();
}

// ==========================================
// 4. Interactions & Events
// ==========================================
function setupEventListeners() {
    // Days Filter Toggle
    daysInput.addEventListener('change', (e) => {
        let val = parseInt(e.target.value);
        if (isNaN(val) || val < 1) val = 1;
        if (val > 30) val = 30;
        config.days = val;
        loadData();
    });

    // View Toggle
    viewToggleBtn.addEventListener('click', () => {
        config.isTimelineMode = !config.isTimelineMode;
        viewText.textContent = config.isTimelineMode ? "플랫 뷰" : "타임라인 뷰";
        buildVisualization();
    });

    // Close Detail Panel
    closePanelBtn.addEventListener('click', () => {
        detailPanel.classList.add('hidden');
        selectedStockName = null;
        updateSelectionHighlight();
        resetHover();
    });
}

function onWindowResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
}

function onMouseMove(event) {
    // Calculate mouse position in normalized device coordinates (-1 to +1)
    mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
    mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;
}

function onClick() {
    if (hoveredMesh && !hoveredMesh.isRing) {
        selectedStockName = hoveredMesh.userData.name;
        updateSelectionHighlight();
        openDetailPanel(hoveredMesh.userData);
        
        const target = hoveredMesh.position;
        gsap.to(controls.target, {
            x: target.x, y: target.y, z: target.z,
            duration: 1, ease: "power2.out"
        });
    } else {
        // Deselect when clicking empty space
        selectedStockName = null;
        updateSelectionHighlight();
        detailPanel.classList.add('hidden');
    }
}

function updateSelectionHighlight() {
    elements.forEach(obj => {
        if (obj.isRing) return;
        
        const mat = obj.mesh.material;
        const color = new THREE.Color(obj.data.baseColor);

        if (!selectedStockName || obj.data.name === selectedStockName) {
            mat.opacity = 0.95;
            mat.color.copy(color);
        } else {
            mat.opacity = 0.2;
            const hsl = {};
            color.getHSL(hsl);
            color.setHSL(hsl.h, 0.0, hsl.l * 0.5); // Desaturate
            mat.color.copy(color);
        }
    });

    lines.forEach(line => {
        if (!selectedStockName || line.userData.name === selectedStockName) {
            line.material.opacity = 0.3;
        } else {
            line.material.opacity = 0.05;
        }
    });
}

function resetHover() {
    if (hoveredMesh && !hoveredMesh.isRing) {
        gsap.to(hoveredMesh.scale, { x: 1, y: 1, z: 1, duration: 0.3 });
        if (selectedStockName && hoveredMesh.userData.name !== selectedStockName) {
            hoveredMesh.material.opacity = 0.2;
        } else {
            hoveredMesh.material.opacity = 0.95;
        }
        document.body.style.cursor = 'default';
        hoveredMesh = null;
    }
}

function openDetailPanel(data) {
    const stockName = data.name;
    const globalStats = dataCache.total[stockName] || data.stats;

    elTitle.textContent = stockName;
    elRec.textContent = globalStats['추천'] || 0;
    elCau.textContent = globalStats['주의'] || 0;
    
    // Generate detailed opinions list
    const ul = document.getElementById('opinion-list');
    ul.innerHTML = ''; // clear previous
    
    if (globalStats.opinions && globalStats.opinions.length > 0) {
        // sort by most recent first
        const sorted = [...globalStats.opinions].sort((a,b) => new Date(b.upload_date) - new Date(a.upload_date));
        
        sorted.forEach(op => {
            const li = document.createElement('li');
            li.className = `opinion-item ${op.opinion_type === '추천' ? 'item-rec' : op.opinion_type === '주의' ? 'item-cau' : ''}`;
            
            const dateStr = new Date(op.upload_date).toLocaleDateString('ko-KR');
            const ytLink = op.video_id ? `<a href="https://youtube.com/watch?v=${op.video_id}" target="_blank" class="yt-link">[유튜브 보기]</a>` : '';
            
            li.innerHTML = `
                <div class="op-header">
                    <span class="op-type">${op.opinion_type}</span>
                    <span class="op-date">${dateStr}</span>
                </div>
                <div class="op-recommender"><strong>전문가/채널:</strong> ${op.recommender || '불명'} ${ytLink}</div>
                <div class="op-reason">${op.reason_summary || '요약 없음'}</div>
            `;
            ul.appendChild(li);
        });
    } else {
        ul.innerHTML = '<li class="hint">상세 의견 데이터가 없습니다.</li>';
    }

    detailPanel.classList.remove('hidden');
}

// ==========================================
// 5. Render Loop
// ==========================================
function animate() {
    requestAnimationFrame(animate);

    controls.update(); 

    raycaster.setFromCamera(mouse, camera);
    
    const interactables = elements.filter(s => !s.isRing).map(s => s.mesh);
    const intersects = raycaster.intersectObjects(interactables);

    if (intersects.length > 0) {
        const object = intersects[0].object;
        if (hoveredMesh !== object) {
            resetHover();
            hoveredMesh = object;
            
            // Hover effect
            document.body.style.cursor = 'pointer';
            gsap.to(hoveredMesh.scale, { x: 1.15, y: 1.15, z: 1.15, duration: 0.3, ease: "back.out(1.7)" });
            hoveredMesh.material.opacity = 1.0;
        }
    } else {
        resetHover();
    }

    renderer.render(scene, camera);
}

// Start
init();
