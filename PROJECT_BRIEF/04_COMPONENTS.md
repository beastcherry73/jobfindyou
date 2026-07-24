# 04_COMPONENTS: Reusable Styling Blueprints

## Component Classes

### 1. Navigation Container (`.landing-nav`)
Fixed positioning, blurred backdrop, thin border, and rounded corners:
```css
.landing-nav {
  position: fixed;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  width: min(90%, 1100px);
  height: 64px;
  background: rgba(8, 17, 31, 0.75);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(124, 200, 255, 0.15);
  border-radius: 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  z-index: 9999;
}
```

### 2. Primary Buttons (`.cta-btn`)
Pill-shaped, bold weight, smooth click transitions:
```css
.cta-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 12px 28px;
  background: #2563EB;
  color: #FFFFFF;
  font-weight: 700;
  font-size: 0.85rem;
  border-radius: 24px;
  text-decoration: none;
  transition: transform 0.2s, box-shadow 0.2s;
  cursor: pointer;
  border: none;
}
.cta-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 20px rgba(37, 99, 235, 0.25);
}
```

### 3. Floating 3D Resume Card (`#hero3dResume`)
Parallax-styled container, light background, soft drop-shadow, with interactive mouse hover:
```css
.float-resume {
  width: 280px;
  height: 380px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 12px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  transform: rotateY(-18deg) rotateX(12deg);
  box-shadow: 20px 30px 60px rgba(0, 0, 0, 0.25);
  padding: 24px;
  transition: transform 0.3s ease-out;
}
```
