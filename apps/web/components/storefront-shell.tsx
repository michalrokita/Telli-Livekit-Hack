'use client';

import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  ArrowRight,
  Minus,
  Plus,
  Search,
  ShoppingBag,
  Sparkles,
  UserRound,
  X,
} from 'lucide-react';

import { StyleConciergeChat } from '@/components/style-concierge-chat';
import {
  deliveryDetails,
  formatPrice,
  getCartTotals,
  getLiveKitReadiness,
  lomaCategories,
  lomaProducts,
  type LomaCartItem,
  type LomaProduct,
} from '@/lib/demo-script';

export function StorefrontShell() {
  const [cartOpen, setCartOpen] = useState(false);
  const [cartItems, setCartItems] = useState<LomaCartItem[]>([]);
  const [badgeBump, setBadgeBump] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const bumpTimerRef = useRef<number | null>(null);

  const readiness = useMemo(
    () => getLiveKitReadiness(process.env.NEXT_PUBLIC_LIVEKIT_URL),
    [],
  );
  const cartTotals = useMemo(() => getCartTotals(cartItems), [cartItems]);
  const hasCart = cartTotals.itemCount > 0;

  useEffect(() => {
    return () => {
      if (bumpTimerRef.current) {
        window.clearTimeout(bumpTimerRef.current);
      }
    };
  }, []);

  function bumpBadge() {
    setBadgeBump(true);

    if (bumpTimerRef.current) {
      window.clearTimeout(bumpTimerRef.current);
    }

    bumpTimerRef.current = window.setTimeout(() => setBadgeBump(false), 650);
  }

  function addToCart(products: LomaProduct[], isTryOn = false) {
    if (products.length === 0) {
      return;
    }

    setCartItems((currentItems) => [
      ...currentItems,
      ...products.map((product, index) => ({
        ...product,
        cartId: `${product.id}-${Date.now()}-${currentItems.length + index}`,
        isTryOn,
      })),
    ]);
    bumpBadge();
  }

  function openChat() {
    setChatOpen(true);
  }

  function closeChat() {
    setChatOpen(false);
  }

  function toggleCart() {
    setCartOpen((current) => !current);
  }

  function closeCart() {
    setCartOpen(false);
  }

  return (
    <main className="loma-shell">
      <header className="loma-nav">
        <div className="nav-left">
          <a className="brand-lockup" href="#top" aria-label="LOMA home">
            <span className="brand-orb" aria-hidden="true" />
            <span className="brand-word">LOMA</span>
          </a>

          <nav className="nav-links" aria-label="Store sections">
            {lomaCategories.map((category) => (
              <a key={category.id} href={`#${category.id}`}>
                {category.navLabel}
              </a>
            ))}
            <a href="#edit">The Edit</a>
            <a href="#about">About</a>
          </nav>
        </div>

        <div className="nav-actions">
          <span
            className={readiness.configured ? 'livekit-pill is-ready' : 'livekit-pill'}
            title={readiness.detail}
          >
            <span aria-hidden="true" />
            {readiness.label}
          </span>
          <button className="nav-text-button" type="button" aria-label="Search catalog">
            <Search size={17} aria-hidden="true" />
            <span>Search</span>
          </button>
          <button className="nav-text-button account-action" type="button" aria-label="Account">
            <UserRound size={17} aria-hidden="true" />
            <span>Account</span>
          </button>
          <button
            className="bag-button"
            type="button"
            aria-label={`${cartTotals.itemCount} items in bag`}
            onClick={toggleCart}
          >
            <ShoppingBag size={22} aria-hidden="true" />
            <AnimatePresence initial={false}>
              {hasCart ? (
                <motion.span
                  key={cartTotals.itemCount}
                  className={badgeBump ? 'bag-badge is-bumping' : 'bag-badge'}
                  initial={{ scale: 0.4, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: 0.4, opacity: 0 }}
                >
                  {cartTotals.itemCount}
                </motion.span>
              ) : null}
            </AnimatePresence>
          </button>
        </div>
      </header>

      <section className="loma-hero" id="top" aria-labelledby="hero-title">
        <div className="hero-copy">
          <p className="hero-kicker">Summer '26 / New arrivals</p>
          <h1 id="hero-title">
            Basics, <em>considered.</em>
            <br />
            Made to be lived in.
          </h1>
          <p className="hero-description">
            Heavyweight cotton tees and clean-lined caps in a warm, wearable palette.
            Or let Mira find your fit.
          </p>
          <div className="hero-actions">
            <a className="primary-cta" href="#edit">
              Shop the edit
              <ArrowRight size={16} aria-hidden="true" />
            </a>
            <button className="secondary-cta" type="button" onClick={openChat}>
              <span aria-hidden="true" />
              Style me with Mira
            </button>
          </div>
        </div>

        <div className="hero-campaign" aria-label="Campaign image - model in clay tee">
          <img
            src="https://images.unsplash.com/photo-1503342217505-b0a15ec3261c?auto=format&fit=crop&w=1200&q=85"
            alt="Editorial campaign model in a warm clay tee"
          />
          <div className="campaign-wash" aria-hidden="true" />
          <span>campaign image - model in clay tee</span>
        </div>
      </section>

      <section className="collection-section" id="edit" aria-labelledby="collection-title">
        <div className="section-title-row">
          <div>
            <p className="section-kicker">The edit</p>
            <h2 id="collection-title">The collection</h2>
          </div>
          <span>{lomaProducts.length} pieces</span>
        </div>

        <div className="product-grid">
          {lomaProducts.map((product) => (
            <ProductTile
              key={product.id}
              product={product}
              onAdd={() => addToCart([product])}
            />
          ))}
        </div>
      </section>

      <section className="about-strip" id="about" aria-label="LOMA service notes">
        <div>
          <span>01</span>
          <strong>Voice-first styling</strong>
          <p>Run the full Mira demo in mock mode, then connect LiveKit when env is ready.</p>
        </div>
        <div>
          <span>02</span>
          <strong>Camera-aware picks</strong>
          <p>The fallback script reads style cues and keeps the cart focused on tees and hats.</p>
        </div>
        <div>
          <span>03</span>
          <strong>Same warm checkout</strong>
          <p>Cart additions, badge motion, delivery details, and pay flow stay in one path.</p>
        </div>
      </section>

      <CartDrawer
        cartItems={cartItems}
        cartOpen={cartOpen}
        subtotal={cartTotals.subtotal}
        onClose={closeCart}
        onOpenChat={openChat}
      />

      <StyleConciergeChat
        cartCount={cartTotals.itemCount}
        chatOpen={chatOpen}
        liveKitReadiness={readiness}
        onAddToCart={addToCart}
        onClose={closeChat}
        onOpen={openChat}
      />
    </main>
  );
}

type ProductTileProps = {
  product: LomaProduct;
  onAdd: () => void;
};

function ProductTile({ product, onAdd }: ProductTileProps) {
  return (
    <motion.article
      className="product-tile"
      style={
        {
          '--tile-color': product.color,
          '--tile-tag-color': product.textColor,
        } as CSSProperties
      }
      whileHover={{ y: -5 }}
      transition={{ type: 'spring', stiffness: 340, damping: 28 }}
    >
      <div className="product-art">
        <img src={product.imageUrl} alt={product.name} />
        <div aria-hidden="true" />
        <span>{product.kind}</span>
        <button className="quick-add" type="button" onClick={onAdd}>
          <Plus size={15} aria-hidden="true" />
          Add
        </button>
      </div>
      <div className="product-line">
        <span>{product.name}</span>
        <span>{formatPrice(product.price)}</span>
      </div>
      <p>{product.sub}</p>
    </motion.article>
  );
}

type CartDrawerProps = {
  cartItems: LomaCartItem[];
  cartOpen: boolean;
  subtotal: number;
  onClose: () => void;
  onOpenChat: () => void;
};

function CartDrawer({
  cartItems,
  cartOpen,
  subtotal,
  onClose,
  onOpenChat,
}: CartDrawerProps) {
  const hasCart = cartItems.length > 0;

  return (
    <AnimatePresence>
      {cartOpen ? (
        <>
          <motion.button
            className="cart-scrim"
            type="button"
            aria-label="Close bag"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />
          <motion.aside
            className="cart-drawer"
            aria-label="Your bag"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', stiffness: 320, damping: 34 }}
          >
            <div className="cart-head">
              <span>Your bag</span>
              <button type="button" aria-label="Close bag" onClick={onClose}>
                <X size={22} aria-hidden="true" />
              </button>
            </div>

            <div className="cart-body loma-scroll">
              {!hasCart ? (
                <div className="empty-bag">
                  <span>
                    <ShoppingBag size={22} aria-hidden="true" />
                  </span>
                  <strong>Your bag is empty</strong>
                  <button type="button" onClick={onOpenChat}>
                    Ask Mira to style you
                  </button>
                </div>
              ) : null}

              {cartItems.map((item) => (
                <div className="cart-line-item" key={item.cartId}>
                  <div
                    className={item.isTryOn ? 'cart-thumb is-tryon' : 'cart-thumb'}
                    style={{ '--thumb-color': item.color } as CSSProperties}
                  >
                    <img src={item.imageUrl} alt="" />
                    {item.isTryOn ? <span>AI TRY-ON</span> : null}
                  </div>
                  <div className="cart-item-copy">
                    <div>
                      <strong>{item.name}</strong>
                      <span>{formatPrice(item.price)}</span>
                    </div>
                    <p>{item.sub}</p>
                    <div className="quantity-control" aria-label={`${item.name} quantity`}>
                      <button type="button" aria-label={`Decrease ${item.name} quantity`}>
                        <Minus size={13} aria-hidden="true" />
                      </button>
                      <span>1</span>
                      <button type="button" aria-label={`Increase ${item.name} quantity`}>
                        <Plus size={13} aria-hidden="true" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {hasCart ? (
              <div className="cart-foot">
                <div>
                  <span>Subtotal</span>
                  <strong>{formatPrice(subtotal)}</strong>
                </div>
                <p>Shipping and taxes calculated at checkout. {deliveryDetails.window}.</p>
                <button type="button">Checkout</button>
              </div>
            ) : null}
          </motion.aside>
        </>
      ) : null}
    </AnimatePresence>
  );
}
