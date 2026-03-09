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
let spheres = []; // Holds references to all mesh objects
let hoveredSphere = null;

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

    // Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    scene.add(ambientLight);

    const pointLight = new THREE.PointLight(0xffffff, 0.6);
    pointLight.position.set(50, 200, 50);
    camera.add(pointLight); // light follows camera attached to scene later
    scene.add(camera);

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
function clearSpheres() {
    spheres.forEach(obj => {
        scene.remove(obj.mesh);
        // Clean up geometry & materials
        obj.mesh.geometry.dispose();
        obj.mesh.material.dispose();
    });
    spheres = [];
}

/** 
 * Calculate sphere color based on recommend/caution ratio
 */
function getColor(rec, cau) {
    if (rec > 0 && cau === 0) return COLOR_RECOMMEND;
    if (cau > 0 && rec === 0) return COLOR_CAUTION;
    if (rec > 0 && cau > 0) return COLOR_MIXED;
    return COLOR_NEUTRAL; // Only '관심'
}

/**
 * 2D Flat Mode: All stocks summarized over the total selected days.
 * Arranged in a spiraling distribution on the XZ plane.
 */
function buildFlatMode() {
    const keys = Object.keys(dataCache.total).sort((a,b) => {
        // Sort by total signals descending
        const totalA = Object.values(dataCache.total[a]).reduce((acc, val)=>acc+val, 0);
        const totalB = Object.values(dataCache.total[b]).reduce((acc, val)=>acc+val, 0);
        return totalB - totalA;
    });

    keys.forEach((stockName, idx) => {
        const stats = dataCache.total[stockName];
        const totalSignals = stats['추천'] + stats['주의'] + stats['관심'];
        
        // Base size logic: larger means more total recommendations
        const radius = Math.max(3, Math.min(20, totalSignals * 2));
        const color = getColor(stats['추천'], stats['주의']);

        // Spiral arrangement
        const phi = idx * 1.375; // golden ratio approx
        const rDist = Math.sqrt(idx) * 15;
        const x = rDist * Math.cos(phi);
        const z = rDist * Math.sin(phi);
        const y = 0; // Flat

        createSphere(stockName, stats, radius, color, x, y, z);
    });
}

/**
 * 3D Timeline Mode: Data bucketed into 12 hour chunks.
 * Standard Y axis mapping (higher up = more recent).
 */
function buildTimelineMode() {
    // Determine max bucket index to scale Y axis appropriately
    const buckets = Object.keys(dataCache.timeline).map(Number).sort((a,b) => a-b);
    if (buckets.length === 0) return;
    
    // We space each 12-hour bucket vertically by 30 units
    const Y_SPACING = 30;
    
    buckets.forEach(bucketIdx => {
        const levelData = dataCache.timeline[bucketIdx];
        const yPos = -bucketIdx * Y_SPACING + 50; // newest at +50, older goes downwards
        
        const stocks = Object.keys(levelData);
        // Distribute stocks in this bucket in a circle
        const numStocks = stocks.length;
        const circleRadius = Math.max(20, numStocks * 4); // expand ring if many stocks
        
        stocks.forEach((stockName, idx) => {
            const stats = levelData[stockName];
            const totalSignals = stats['추천'] + stats['주의'] + stats['관심'];
            
            const radius = Math.max(2, Math.min(15, totalSignals * 2));
            const color = getColor(stats['추천'], stats['주의']);
            
            const angle = (idx / numStocks) * Math.PI * 2;
            const x = circleRadius * Math.cos(angle);
            const z = circleRadius * Math.sin(angle);
            
            createSphere(stockName, stats, radius, color, x, yPos, z);
        });
        
        // Add a subtle ring to delineate the time period visually
        const ringGeo = new THREE.RingGeometry(circleRadius - 0.5, circleRadius + 0.5, 64);
        const ringMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.1, side: THREE.DoubleSide });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.rotation.x = Math.PI / 2;
        ring.position.y = yPos;
        scene.add(ring);
        // Hack: track rings to remove them later when rebuilding
        spheres.push({ mesh: ring, isRing: true }); 
    });
}

function createSphere(name, stats, radius, colorHex, tx, ty, tz) {
    const geometry = new THREE.SphereGeometry(radius, 32, 32);
    
    // Premium glowing material using MeshPhysicalMaterial
    const material = new THREE.MeshPhysicalMaterial({
        color: colorHex,
        emissive: colorHex,
        emissiveIntensity: 0.5,
        roughness: 0.2,
        metalness: 0.8,
        transmission: 0.5, // glass effect
        opacity: 0.9,
        transparent: true
    });

    const mesh = new THREE.Mesh(geometry, material);
    
    // Initial position for intro animation (drop from above)
    mesh.position.set(tx, ty + 200, tz);
    
    // Data attached to mesh for hover/click interaction
    mesh.userData = {
        name: name,
        stats: stats,
        baseColor: colorHex,
        targetPos: new THREE.Vector3(tx, ty, tz),
        baseScale: new THREE.Vector3(1, 1, 1)
    };

    scene.add(mesh);
    spheres.push({ mesh, data: mesh.userData });

    // Intro Animation using GSAP
    gsap.to(mesh.position, {
        x: tx, y: ty, z: tz,
        duration: 1.5,
        ease: "bounce.out",
        delay: Math.random() * 0.5 // staggered drop
    });
}

function buildVisualization() {
    clearSpheres();

    if (config.isTimelineMode) {
        buildTimelineMode();
        // Adjust camera to view vertical stack better
        gsap.to(camera.position, { x: 150, y: 50, z: 250, duration: 1.5 });
    } else {
        buildFlatMode();
        // Top-down angled view
        gsap.to(camera.position, { x: 0, y: 150, z: 200, duration: 1.5 });
    }
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
    if (hoveredSphere && !hoveredSphere.isRing) {
        openDetailPanel(hoveredSphere.userData);
        
        // Animate camera to look at the clicked sphere (but keep distance)
        const target = hoveredSphere.position;
        gsap.to(controls.target, {
            x: target.x, y: target.y, z: target.z,
            duration: 1, ease: "power2.out"
        });
    }
}

function resetHover() {
    if (hoveredSphere && !hoveredSphere.isRing) {
        gsap.to(hoveredSphere.scale, { x: 1, y: 1, z: 1, duration: 0.3 });
        hoveredSphere.material.emissiveIntensity = 0.5;
        document.body.style.cursor = 'default';
        hoveredSphere = null;
    }
}

function openDetailPanel(data) {
    const { name, stats } = Object.keys(dataCache.total).includes(data.name) 
                            ? { name: data.name, stats: dataCache.total[data.name] } 
                            : data;

    elTitle.textContent = name;
    elRec.textContent = stats['추천'] || 0;
    elCau.textContent = stats['주의'] || 0;
    
    detailPanel.classList.remove('hidden');
}

// ==========================================
// 5. Render Loop
// ==========================================
function animate() {
    requestAnimationFrame(animate);

    controls.update(); // required if damping enabled

    // Hover Raycasting Logic
    raycaster.setFromCamera(mouse, camera);
    
    // Filter out rings from intersection testing
    const interactables = spheres.filter(s => !s.isRing).map(s => s.mesh);
    const intersects = raycaster.intersectObjects(interactables);

    if (intersects.length > 0) {
        const object = intersects[0].object;
        if (hoveredSphere !== object) {
            resetHover();
            hoveredSphere = object;
            
            // Hover effect
            document.body.style.cursor = 'pointer';
            gsap.to(hoveredSphere.scale, { x: 1.3, y: 1.3, z: 1.3, duration: 0.3, ease: "back.out(1.7)" });
            hoveredSphere.material.emissiveIntensity = 1.0;
        }
    } else {
        resetHover();
    }

    // Subtle floating animation for all spheres
    const time = Date.now() * 0.001;
    spheres.forEach((s, i) => {
        if (!s.isRing && s.mesh.userData.targetPos) {
            // Sine wave floating effect based on base position
            s.mesh.position.y = s.mesh.userData.targetPos.y + Math.sin(time * 2 + i) * 2;
        }
    });

    renderer.render(scene, camera);
}

// Start
init();
